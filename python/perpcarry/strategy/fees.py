"""M7-T4: explicit dated taker fees, without a historical-rate fallback."""

import tomllib
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Literal

Market = Literal["spot", "perp"]


def decimal(value: Decimal, name: str, *, positive: bool = False) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{name} must be a finite Decimal")
    if positive and value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def timestamp(value: int, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a nonnegative millisecond integer")
    return value


@dataclass(frozen=True)
class FeePeriod:
    symbol: str
    market: Market
    start_ms: int
    end_ms: int
    taker_fraction: Decimal
    source: str
    observed_at_ms: int
    kind: Literal["verified", "assumption"]

    def __post_init__(self):
        timestamp(self.start_ms, "start_ms")
        timestamp(self.end_ms, "end_ms")
        timestamp(self.observed_at_ms, "observed_at_ms")
        decimal(self.taker_fraction, "taker_fraction")
        if (
            not isinstance(self.symbol, str)
            or not self.symbol
            or self.market not in ("spot", "perp")
            or self.end_ms <= self.start_ms
            or not 0 <= self.taker_fraction < 1
            or not isinstance(self.source, str)
            or not self.source.startswith("https://")
            or self.kind not in ("verified", "assumption")
        ):
            raise ValueError("Invalid fee period or provenance")


@dataclass(frozen=True)
class FeeSchedule:
    periods: tuple[FeePeriod, ...]
    allow_assumptions: bool = False

    def __post_init__(self):
        if type(self.allow_assumptions) is not bool or not isinstance(self.periods, tuple):
            raise ValueError("Fee periods must be immutable; assumption admission must be boolean")
        if not self.periods or any(not isinstance(p, FeePeriod) for p in self.periods):
            raise ValueError("Fee schedule needs fee periods")
        for i, left in enumerate(self.periods):
            for right in self.periods[i + 1 :]:
                if (left.symbol, left.market) == (right.symbol, right.market) and max(
                    left.start_ms, right.start_ms
                ) < min(left.end_ms, right.end_ms):
                    raise ValueError("Overlapping fee periods")

    def quote(self, symbol: str, market: Market, time_ms: int) -> Decimal:
        timestamp(time_ms, "time_ms")
        for period in self.periods:
            if (
                period.symbol == symbol
                and period.market == market
                and period.start_ms <= time_ms < period.end_ms
            ):
                if period.kind == "assumption":
                    if not self.allow_assumptions:
                        raise ValueError("Unverified fee assumption requires explicit admission")
                elif period.observed_at_ms > time_ms:
                    raise ValueError("Fee evidence is in the future")
                return period.taker_fraction
        raise ValueError("No fee coverage for symbol, market and time")


def load_schedule(path: Path, *, allow_assumptions: bool = False) -> FeeSchedule:
    """Load cited reference/sensitivity inputs; this does not certify venue history."""
    document = tomllib.loads(Path(path).read_text())
    if type(document.get("schema_version")) is not int or document["schema_version"] != 1:
        raise ValueError("Unsupported fee schedule schema")
    if not isinstance(document.get("periods"), list) or any(
        not isinstance(row, dict) or not isinstance(row.get("taker_fraction"), str)
        for row in document["periods"]
    ):
        raise ValueError("Fee fractions must be decimal strings in explicit periods")
    return FeeSchedule(
        tuple(
            FeePeriod(**{**row, "taker_fraction": Decimal(row["taker_fraction"])})
            for row in document["periods"]
        ),
        allow_assumptions=allow_assumptions,
    )
