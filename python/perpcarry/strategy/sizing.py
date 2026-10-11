"""M7-T2: discrete profit-optimal sizing inside admitted impact and market limits."""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, localcontext

import numpy as np

from perpcarry.models.rolling_funding import DAY_MS
from perpcarry.strategy import costs
from perpcarry.strategy.carry import (
    CarryStrategy,
    CostEstimate,
    Decision,
    FundingApproval,
    FundingForecast,
    integer,
    number,
)


@dataclass(frozen=True)
class ExecutionCharges:
    entry_half_spread_bps: float
    close_half_spread_bps: float
    entry_fee_bps: float
    close_fee_bps: float
    hedge_entry_bps: float
    hedge_close_bps: float
    financing_fraction: float

    def __post_init__(self):
        for name, value in asdict(self).items():
            number(value, name)
        number(self.fixed_fraction, "summed charges")

    @property
    def fixed_fraction(self):
        return (
            sum(
                value / 10_000
                for name, value in asdict(self).items()
                if name != "financing_fraction"
            )
            + self.financing_fraction
        )


@dataclass(frozen=True)
class SizingInputs:
    symbol: str
    observed_at_ms: int
    valid_until_ms: int
    price_usdt: float
    adv_base: float
    adv_start_ms: int
    adv_end_exclusive_ms: int
    adv_sha256: str
    quantity_step: Decimal
    min_quantity: Decimal
    min_notional_usdt: float
    max_notional_usdt: float
    max_adv_fraction: float
    validated_quantity_base: float
    metadata_valid_from_ms: int
    metadata_valid_until_ms: int
    metadata_sha256: str

    def __post_init__(self):
        if not isinstance(self.symbol, str) or not self.symbol:
            raise ValueError("symbol required")
        for name in (
            "observed_at_ms",
            "adv_start_ms",
            "adv_end_exclusive_ms",
            "metadata_valid_from_ms",
            "metadata_valid_until_ms",
        ):
            integer(getattr(self, name), name)
        integer(self.valid_until_ms, "valid_until_ms", self.observed_at_ms + 1)
        if self.metadata_valid_until_ms <= self.metadata_valid_from_ms:
            raise ValueError("nonempty metadata validity interval required")
        if (
            self.adv_end_exclusive_ms % DAY_MS
            or self.adv_start_ms % DAY_MS
            or self.adv_end_exclusive_ms - self.adv_start_ms != 30 * DAY_MS
        ):
            raise ValueError("complete 30-day UTC ADV window required")
        for name in (
            "price_usdt",
            "adv_base",
            "max_notional_usdt",
            "max_adv_fraction",
            "validated_quantity_base",
            "min_notional_usdt",
        ):
            number(getattr(self, name), name)
            if name != "min_notional_usdt" and getattr(self, name) == 0:
                raise ValueError(f"{name} must be positive")
        for name in ("quantity_step", "min_quantity"):
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
                raise ValueError(f"{name} must be a finite nonnegative Decimal")
        if self.quantity_step == 0:
            raise ValueError("positive quantity step required")
        for name in ("adv_sha256", "metadata_sha256"):
            if not isinstance(getattr(self, name), str) or not re.fullmatch(
                r"[0-9a-f]{64}", getattr(self, name)
            ):
                raise ValueError(f"{name} must identify admitted evidence")


@dataclass(frozen=True)
class SizingResult:
    quantity_base: Decimal
    notional_usdt: float
    adv_fraction: float
    expected_net_usdt: float
    marginal_net_fraction: float | None
    decision: Decision
    cost_estimate: CostEstimate | None = None
    feasible_max_adv_fraction: float | None = None
    break_even_adv_fraction: float | None = None
    break_even_status: str = "unavailable"
    binding_limits: tuple[str, ...] = ()
    feasible_max_notional_usdt: float | None = None
    break_even_notional_usdt: float | None = None


def size_position(
    strategy: CarryStrategy,
    *,
    now_ms: int,
    forecast: FundingForecast | None,
    approval: FundingApproval | None,
    market: SizingInputs,
    curve: costs.ImpactCurve,
    charges: ExecutionCharges,
) -> SizingResult:
    """Size a flat candidate only. Actual fills and capital accounting belong to T3/T4."""
    integer(now_ms, "now_ms")

    def empty(reason, decision=None):
        return SizingResult(Decimal(0), 0.0, 0.0, 0.0, None, decision or Decision("wait", reason))

    if (
        market.symbol != strategy.symbol
        or curve.symbol != strategy.symbol
        or market.observed_at_ms > now_ms
        or now_ms >= market.valid_until_ms
        or market.adv_end_exclusive_ms != now_ms // DAY_MS * DAY_MS
        or not market.metadata_valid_from_ms <= now_ms < market.metadata_valid_until_ms
        or curve.admitted_at_ms > now_ms
        or curve.evidence_end_exclusive_ms > now_ms
    ):
        return empty("sizing_inputs_not_admitted")
    # Decimal bounds enforce the supplied contract even at fractional-lot boundaries.
    with localcontext() as context:
        context.prec = 60
        adv, price = Decimal(str(market.adv_base)), Decimal(str(market.price_usdt))
        step = market.quantity_step
        limits = {
            "model_support": Decimal(str(curve.size_max)) * adv,
            "validated_depth": Decimal(str(market.validated_quantity_base)),
            "max_adv": Decimal(str(market.max_adv_fraction)) * adv,
            "max_notional": Decimal(str(market.max_notional_usdt)) / price,
        }
        upper = min(limits.values())
        lower = max(
            Decimal(str(curve.size_min)) * adv,
            market.min_quantity,
            Decimal(str(market.min_notional_usdt)) / price,
        )
        first = max(1, int((lower / step).to_integral_value(rounding=ROUND_CEILING)))
        last = int((upper / step).to_integral_value(rounding=ROUND_FLOOR))
        if first > last:
            return empty("no_executable_size")

        def quote(lots):
            quantity = step * lots
            fraction, notional = float(quantity / adv), float(quantity * price)
            estimate = costs.from_curve(
                curve,
                now_ms=now_ms,
                valid_until_ms=market.valid_until_ms,
                notional_usdt=notional,
                adv_fraction=fraction,
                horizon_settlements=strategy.policy.horizon_settlements,
                **asdict(charges),
            )
            decision = strategy.decide(
                now_ms=now_ms, forecast=forecast, costs=estimate, approval=approval
            )
            return quantity, fraction, estimate, decision

        _, _, _, minimum_decision = quote(first)
        if minimum_decision.action != "enter":
            return empty(minimum_decision.reason, minimum_decision)
        # All further candidates share admitted evidence; nonnegative costs make the gate monotone.
        low, high = first, last
        while low < high:
            middle = (low + high + 1) // 2
            if quote(middle)[3].action == "enter":
                low = middle
            else:
                high = middle - 1
        feasible_last = low
        max_fraction = float(step * feasible_last / adv)
        mu = float(np.asarray(forecast.prediction.samples, dtype=float).mean())
        edge, coefficient = mu - charges.fixed_fraction, curve.round_trip_coefficient
        if not math.isfinite(coefficient):
            return empty("nonfinite_impact_coefficient")
        if coefficient == 0 or edge >= 1.5 * coefficient * math.sqrt(max_fraction):
            target = feasible_last
        else:
            optimum = (edge / (1.5 * coefficient)) ** 2
            target = int(
                (Decimal(str(optimum)) * adv / step).to_integral_value(rounding=ROUND_FLOOR)
            )
        candidates = sorted(
            {max(first, min(feasible_last, target)), max(first, min(feasible_last, target + 1))}
        )
        best = None
        for lots in candidates:
            quantity, fraction, estimate, decision = quote(lots)
            profit = estimate.notional_usdt * decision.expected_incremental_fraction
            if not math.isfinite(profit):
                return empty("nonfinite_expected_profit")
            if best is None or profit > best[0]:
                best = (profit, quantity, fraction, estimate, decision)
        profit, quantity, fraction, estimate, decision = best
        # Minimum was profitable; a zero alternative still protects against numeric degeneration.
        if profit <= 0:
            return empty("nonpositive_expected_profit")
        if coefficient == 0:
            root, root_status = None, "no_finite_root"
        elif edge < coefficient * math.sqrt(curve.size_min):
            root, root_status = None, "below_support"
        elif edge > coefficient * math.sqrt(curve.size_max):
            root, root_status = None, "above_support"
        else:
            root, root_status = (edge / coefficient) ** 2, "within_support"
        labels = (
            ("entry_gate",)
            if feasible_last < last
            else tuple(name for name, bound in limits.items() if bound == upper)
        )
        marginal = edge - 1.5 * coefficient * math.sqrt(fraction)
        root_notional = float(Decimal(str(root)) * adv * price) if root is not None else None
        if root_notional is not None and not math.isfinite(root_notional):
            root_notional = None
        return SizingResult(
            quantity,
            estimate.notional_usdt,
            fraction,
            profit,
            marginal,
            decision,
            estimate,
            max_fraction,
            root,
            root_status,
            labels,
            float(step * feasible_last * price),
            root_notional,
        )
