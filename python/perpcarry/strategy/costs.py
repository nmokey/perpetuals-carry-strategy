"""M7-T1/T2: admit prior impact artifacts and build fraction-unit execution estimates."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

from perpcarry.ingestion.funding_series import utc_ms
from perpcarry.integrity import sha256
from perpcarry.models import impact_model_io
from perpcarry.models.impact_model import ImpactModelError
from perpcarry.strategy.carry import CostEstimate, integer, number


def from_artifact(
    path: Path,
    *,
    symbol: str,
    now_ms: int,
    valid_until_ms: int,
    notional_usdt: float,
    adv_fraction: float,
    horizon_settlements: int,
    schedule: str,
    depth: str,
    size_regime: str,
    entry_half_spread_bps: float,
    close_half_spread_bps: float,
    entry_fee_bps: float,
    close_fee_bps: float,
    hedge_entry_bps: float,
    hedge_close_bps: float,
    financing_fraction: float,
    allow_synthetic: bool = False,
) -> CostEstimate:
    """Sell perp to open / buy to close. Terminal cost is today's close-cost estimate."""
    integer(now_ms, "now_ms")
    for name, value in (
        ("adv_fraction", adv_fraction),
        ("entry_half_spread_bps", entry_half_spread_bps),
        ("close_half_spread_bps", close_half_spread_bps),
        ("entry_fee_bps", entry_fee_bps),
        ("close_fee_bps", close_fee_bps),
        ("hedge_entry_bps", hedge_entry_bps),
        ("hedge_close_bps", hedge_close_bps),
        ("financing_fraction", financing_fraction),
    ):
        number(value, name)
    if adv_fraction == 0 or type(allow_synthetic) is not bool:
        raise ValueError("positive size and explicit synthetic policy required")
    curve = load_curve(
        path,
        symbol=symbol,
        now_ms=now_ms,
        schedule=schedule,
        depth=depth,
        size_regime=size_regime,
        allow_synthetic=allow_synthetic,
    )
    return from_curve(
        curve,
        now_ms=now_ms,
        valid_until_ms=valid_until_ms,
        notional_usdt=notional_usdt,
        adv_fraction=adv_fraction,
        horizon_settlements=horizon_settlements,
        entry_half_spread_bps=entry_half_spread_bps,
        close_half_spread_bps=close_half_spread_bps,
        entry_fee_bps=entry_fee_bps,
        close_fee_bps=close_fee_bps,
        hedge_entry_bps=hedge_entry_bps,
        hedge_close_bps=hedge_close_bps,
        financing_fraction=financing_fraction,
    )


def load_curve(
    path: Path,
    *,
    symbol: str,
    now_ms: int,
    schedule: str,
    depth: str,
    size_regime: str,
    allow_synthetic: bool = False,
) -> ImpactCurve:
    """Load both supported primary laws once; no extrapolation or default substitution."""
    integer(now_ms, "now_ms")
    if type(allow_synthetic) is not bool:
        raise ValueError("explicit synthetic policy required")
    if depth != "inside_validated_depth":
        raise ImpactModelError("initial strategy costs require explicitly validated order depth")
    digest = sha256(path)
    artifact = impact_model_io.load(path)
    if sha256(path) != digest:
        raise ImpactModelError("impact artifact changed while reading")
    evidence_end = utc_ms(dt.date.fromisoformat(artifact["test_end_exclusive"]))
    if artifact["symbol"] != symbol or evidence_end > now_ms:
        raise ImpactModelError("symbol mismatch or future calibration/validation evidence")
    kind = artifact["provenance"]["kind"]
    if kind == "synthetic" and not allow_synthetic:
        raise ImpactModelError("synthetic impact artifact is not a research cost model")
    coefficients, minima, maxima = {}, [], []
    for side in ("sell", "buy"):
        law = impact_model_io.law(
            artifact,
            side=side,
            schedule=schedule,
            depth=depth,
            size_regime=size_regime,
        )
        record = next(
            f
            for f in artifact["fits"]
            if (f["side"], f["schedule"], f["depth"], f["size_regime"], f["model"]["form"])
            == (side, schedule, depth, size_regime, "square_root")
        )
        if not record["usable_as_nonnegative_impact_law"] or law.coefficient < 0:
            raise ImpactModelError("unusable or extrapolated impact stratum")
        coefficients[side] = law.coefficient
        minima.append(record["training_size_min"])
        maxima.append(record["training_size_max"])
    lower, upper = max(minima), min(maxima)
    if lower > upper:
        raise ImpactModelError("no common supported size range")
    return ImpactCurve(
        symbol,
        now_ms,
        evidence_end,
        digest,
        kind,
        coefficients["sell"],
        coefficients["buy"],
        lower,
        upper,
    )


@dataclass(frozen=True)
class ImpactCurve:
    symbol: str
    admitted_at_ms: int
    evidence_end_exclusive_ms: int
    artifact_sha256: str
    kind: str
    sell_coefficient_bps: float
    buy_coefficient_bps: float
    size_min: float
    size_max: float

    def __post_init__(self):
        CostEstimate(
            self.symbol,
            1.0,
            1,
            self.admitted_at_ms,
            self.admitted_at_ms + 1,
            self.evidence_end_exclusive_ms,
            self.artifact_sha256,
            self.kind,
            0.0,
            0.0,
            0.0,
            0.0,
        )
        for name in ("sell_coefficient_bps", "buy_coefficient_bps", "size_min", "size_max"):
            number(getattr(self, name), name)
        if not 0 < self.size_min <= self.size_max:
            raise ImpactModelError("invalid supported size range")

    @property
    def round_trip_coefficient(self):
        return self.sell_coefficient_bps / 10_000 + self.buy_coefficient_bps / 10_000


def from_curve(
    curve: ImpactCurve,
    *,
    now_ms: int,
    valid_until_ms: int,
    notional_usdt: float,
    adv_fraction: float,
    horizon_settlements: int,
    entry_half_spread_bps: float,
    close_half_spread_bps: float,
    entry_fee_bps: float,
    close_fee_bps: float,
    hedge_entry_bps: float,
    hedge_close_bps: float,
    financing_fraction: float,
) -> CostEstimate:
    integer(now_ms, "now_ms")
    number(adv_fraction, "adv_fraction")
    if curve.admitted_at_ms > now_ms or curve.evidence_end_exclusive_ms > now_ms:
        raise ImpactModelError("future curve admission/evidence")
    if not curve.size_min <= adv_fraction <= curve.size_max:
        raise ImpactModelError("extrapolated impact stratum")
    for name, value in (
        ("entry_half_spread_bps", entry_half_spread_bps),
        ("close_half_spread_bps", close_half_spread_bps),
        ("entry_fee_bps", entry_fee_bps),
        ("close_fee_bps", close_fee_bps),
        ("hedge_entry_bps", hedge_entry_bps),
        ("hedge_close_bps", hedge_close_bps),
        ("financing_fraction", financing_fraction),
    ):
        number(value, name)
    entry = (
        curve.sell_coefficient_bps * adv_fraction**0.5
        + entry_half_spread_bps
        + entry_fee_bps
        + hedge_entry_bps
    ) / 10_000
    close = (
        curve.buy_coefficient_bps * adv_fraction**0.5
        + close_half_spread_bps
        + close_fee_bps
        + hedge_close_bps
    ) / 10_000
    return CostEstimate(
        curve.symbol,
        notional_usdt,
        horizon_settlements,
        now_ms,
        valid_until_ms,
        curve.evidence_end_exclusive_ms,
        curve.artifact_sha256,
        curve.kind,
        entry,
        close,
        close,
        financing_fraction,
    )
