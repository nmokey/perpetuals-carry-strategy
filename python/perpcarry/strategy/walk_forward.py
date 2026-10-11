"""M7-T3: lazy chronological decisions and cash accounting, without future suffix reads."""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import asdict, dataclass, replace
from decimal import Context, Decimal, localcontext

from perpcarry.models.funding_model import Prior
from perpcarry.models.impact_model import ImpactModelError
from perpcarry.models.rolling_funding import (
    DAY_MS,
    HOUR_MS,
    FundingModelUnavailable,
    RollingFundingModel,
)
from perpcarry.strategy import costs, funding, sizing
from perpcarry.strategy.accounting import (
    SETTLEMENT_GUARD_MS,
    FundingSettlement,
    Ledger,
    Marks,
    Valuation,
)
from perpcarry.strategy.carry import (
    CarryStrategy,
    Decision,
    FundingApproval,
    Policy,
    Position,
    integer,
)
from perpcarry.strategy.execution import ExecutionUnavailable
from perpcarry.strategy.fees import FeeSchedule, decimal


def fold_start(time_ms: int) -> int:
    date = dt.datetime.fromtimestamp(time_ms / 1000, dt.UTC).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    return int(date.timestamp() * 1000)


@dataclass(frozen=True)
class Config:
    symbol: str
    warmup_start_ms: int
    start_ms: int
    end_ms: int
    initial_capital_usdt: Decimal
    collateral_fraction: Decimal
    policy: Policy
    execution_mode: str
    seed: int = 703
    draws: int = 4096
    rolling_days: int = 90
    min_settlements: int = 30
    interval_hours: int = 8
    prior: Prior = Prior()
    impact_rolling_days: int = 90
    decision_delay_ms: int = 16000

    def __post_init__(self):
        for name in ("warmup_start_ms", "start_ms", "end_ms", "seed"):
            integer(getattr(self, name), name)
        for name, minimum in (
            ("draws", 2),
            ("rolling_days", 1),
            ("impact_rolling_days", 1),
            ("min_settlements", 3),
            ("interval_hours", 1),
        ):
            integer(getattr(self, name), name, minimum)
        decimal(self.initial_capital_usdt, "initial_capital_usdt", positive=True)
        decimal(self.collateral_fraction, "collateral_fraction", positive=True)
        integer(self.decision_delay_ms, "decision_delay_ms", SETTLEMENT_GUARD_MS + 1)
        if (
            self.symbol not in ("BTCUSDT", "SOLUSDT")
            or not self.warmup_start_ms < self.start_ms < self.end_ms
            or self.start_ms != fold_start(self.start_ms)
            or self.end_ms != fold_start(self.end_ms)
            or self.interval_hours > 24
            or 24 % self.interval_hours
            or self.decision_delay_ms >= self.interval_hours * HOUR_MS - SETTLEMENT_GUARD_MS
            or self.warmup_start_ms % (self.interval_hours * HOUR_MS)
            or self.collateral_fraction > 1
            or self.execution_mode not in ("inferred", "book")
            or not isinstance(self.policy, Policy)
            or not isinstance(self.prior, Prior)
        ):
            raise ValueError("Invalid run scope, monthly boundaries, capital or execution policy")


@dataclass(frozen=True)
class FundingEvent:
    event_id: str
    time_ms: int  # Nominal time, with source jitter validated before this API.
    rate: Decimal
    interval_hours: int
    mark_price: Decimal | None  # Warmup can omit marks while flat and unscored.


@dataclass(frozen=True)
class Opportunity:
    fold_start_ms: int
    curve: costs.ImpactCurve
    approval: FundingApproval | None
    market: sizing.SizingInputs
    perp_half_spread_bps: float
    spot_execution_bps: float
    financing_fraction: float

    def __post_init__(self):
        # Validate explicit charges using the existing T2 contract.
        sizing.ExecutionCharges(
            self.perp_half_spread_bps,
            self.perp_half_spread_bps,
            0.0,
            0.0,
            self.spot_execution_bps,
            self.spot_execution_bps,
            self.financing_fraction,
        )


@dataclass(frozen=True)
class MarketEvent:
    event_id: str
    time_ms: int
    spot_mid: Decimal
    perp_mid: Decimal
    marks: Marks
    opportunity: Opportunity | None
    decide: bool
    financing_usdt: Decimal


@dataclass(frozen=True)
class Record:
    event_id: str
    time_ms: int
    fold_start_ms: int
    event_type: str
    decision: Decision | None
    valuation: Valuation | None
    planned_settlements: int | None
    settlements_held: int
    quantity_base: Decimal
    adv_fraction: float | None
    notional_usdt: Decimal | None
    impact_sha256: str | None
    funding_approval_sha256: str | None
    forecast: dict | None
    execution_mode: str
    cash_usdt: Decimal
    funding_usdt: Decimal
    evidence_admitted: bool
    sizing: dict | None


class _Runner:
    def __init__(self, config, fees, executor):
        if executor.mode != config.execution_mode:
            raise ValueError("Execution mode does not match configured backend")
        self.config, self.fees, self.executor = config, fees, executor
        self.model = RollingFundingModel(
            rolling_days=config.rolling_days,
            min_settlements=config.min_settlements,
            prior=config.prior,
        )
        self.strategy = CarryStrategy(config.symbol, config.policy)
        self.ledger = Ledger.start(
            config.symbol, config.initial_capital_usdt, config.start_ms, fees
        )
        self.position = None
        self.last_time = config.warmup_start_ms
        self.next_observation_ms = config.warmup_start_ms
        self.ids = set()
        self.fold_curves = {}
        self.next_decision_ms = config.start_ms + config.decision_delay_ms

    def process(self, event):
        config = self.config
        integer(event.time_ms, "event time")
        if (
            not isinstance(event.event_id, str)
            or not event.event_id
            or event.event_id in self.ids
            or event.time_ms < self.last_time
        ):
            raise ValueError("Duplicate/backwards event stream")
        if not config.warmup_start_ms <= event.time_ms < config.end_ms:
            raise ValueError("Event outside configured warmup/study window")
        self.last_time = event.time_ms
        self.ids.add(event.event_id)
        if event.time_ms >= config.start_ms and event.time_ms > self.next_decision_ms:
            raise ValueError("Missing scheduled decision before this event")
        if isinstance(event, FundingEvent):
            decimal(event.rate, "funding rate")
            if (
                type(event.interval_hours) is not int
                or event.interval_hours != config.interval_hours
                or event.time_ms != self.next_observation_ms
            ):
                raise ValueError("Missing/misaligned funding or unsupported cadence change")
            # Account only observations now available. No current target enters an earlier decision.
            if event.time_ms >= config.start_ms:
                self.ledger = self.ledger.settle(
                    FundingSettlement(
                        event.event_id,
                        config.symbol,
                        event.time_ms,
                        event.interval_hours,
                        event.rate,
                        event.mark_price,
                    )
                )
                self.reserve(event.mark_price)
                if self.position is not None:
                    self.position = replace(
                        self.position, settlements_held=self.position.settlements_held + 1
                    )
            self.model.update(event.time_ms, float(event.rate), event.interval_hours)
            self.next_observation_ms += event.interval_hours * HOUR_MS
            if event.time_ms < config.start_ms:
                return None
            return self.record(event, "funding", None, None, None, None)
        if not isinstance(event, MarketEvent):
            raise ValueError("Unsupported event type")
        if event.time_ms < config.start_ms:
            raise ValueError("Warmup accepts funding only; no warmup trading")
        decimal(event.spot_mid, "spot execution mid", positive=True)
        decimal(event.perp_mid, "perp execution mid", positive=True)
        decimal(event.financing_usdt, "realized financing")
        if (
            type(event.decide) is not bool
            or event.marks.time_ms != event.time_ms
            or event.marks.symbol != config.symbol
        ):
            raise ValueError("Valuation marks or decision scope disagree")
        if event.decide and (
            self.ledger.last_funding_ms is None
            or event.time_ms - self.ledger.last_funding_ms <= SETTLEMENT_GUARD_MS
        ):
            raise ValueError("Decision precedes conservative settlement availability boundary")
        if (event.decide and event.time_ms != self.next_decision_ms) or (
            not event.decide and event.time_ms == self.next_decision_ms
        ):
            raise ValueError("Market event does not match scheduled decision")
        self.ledger = self.ledger.finance(
            f"{event.event_id}:finance", event.time_ms, event.financing_usdt
        )
        valuation = self.ledger.value(event.marks)
        self.reserve(event.marks.perp)
        if valuation.net_equity_usdt <= 0:
            raise ExecutionUnavailable("Nonpositive equity; liquidation is not simulated")
        decision, forecast, result = None, None, None
        if event.decide:
            remaining = (
                self.position.planned_settlements - self.position.settlements_held
                if self.position
                else config.policy.horizon_settlements
            )
            if remaining > 0:
                digest = hashlib.sha256(f"{config.seed}:{config.symbol}:{event.time_ms}".encode())
                seed = int.from_bytes(digest.digest()[:4], "big")
                try:
                    forecast = funding.from_model(
                        config.symbol,
                        self.model,
                        horizon=remaining,
                        now_ms=event.time_ms,
                        draws=config.draws,
                        seed=seed,
                    )
                except FundingModelUnavailable:
                    forecast = None
            opportunity = self.admit(event)
            if self.position is None:
                decision, result = self.enter(event, opportunity, forecast)
            else:
                decision = self.held(event, opportunity, forecast, remaining)
        valuation = self.ledger.value(event.marks)
        self.reserve(event.marks.perp)
        if event.decide:
            self.next_decision_ms += config.interval_hours * HOUR_MS
        return self.record(event, "market", decision, valuation, forecast, result)

    def enter(self, event, opportunity, forecast):
        config = self.config
        result = None
        if opportunity is None:
            decision = Decision("wait", "market_evidence_unavailable")
        else:
            charges = self.charges(event, opportunity)
            spot_fee = self.fees.quote(config.symbol, "spot", event.time_ms)
            perp_fee = self.fees.quote(config.symbol, "perp", event.time_ms)
            per_unit = (
                event.spot_mid
                * (1 + Decimal(str(opportunity.spot_execution_bps)) / 10000)
                * (1 + spot_fee)
            )
            worst_impact = (
                Decimal(
                    str(
                        opportunity.curve.sell_coefficient_bps * opportunity.curve.size_max**0.5
                        + opportunity.perp_half_spread_bps
                    )
                )
                / 10000
            )
            per_unit += event.marks.perp * config.collateral_fraction
            per_unit += max(Decimal(0), event.marks.perp - event.perp_mid)
            per_unit += event.perp_mid * (worst_impact + perp_fee)
            # Reserve adverse entry P&L as well as spot cash and derivative collateral.
            cap = max(Decimal(0), self.ledger.cash_usdt) / per_unit * event.perp_mid
            if cap <= 0:
                decision = Decision("wait", "capital_unavailable")
            else:
                market = replace(
                    opportunity.market,
                    max_notional_usdt=min(opportunity.market.max_notional_usdt, float(cap)),
                )
                result = sizing.size_position(
                    self.strategy,
                    now_ms=event.time_ms,
                    forecast=forecast,
                    approval=opportunity.approval,
                    market=market,
                    curve=opportunity.curve,
                    charges=charges,
                )
                decision = result.decision
                if decision.action == "enter":
                    quantity = result.quantity_base
                    if self.trade(event, quantity, opening=True):
                        self.position = Position(
                            config.symbol,
                            float(quantity * event.perp_mid),
                            event.time_ms,
                            config.policy.horizon_settlements,
                            0,
                            config.interval_hours,
                        )
                    else:
                        decision = Decision("wait", "actual_fill_capital_unavailable")
        return decision, result

    def held(self, event, opportunity, forecast, remaining):
        quantity = -self.ledger.perp.quantity
        position = replace(self.position, notional_usdt=float(quantity * event.perp_mid))
        estimate = None
        if opportunity is not None and remaining > 0:
            try:
                estimate = costs.from_curve(
                    opportunity.curve,
                    now_ms=event.time_ms,
                    valid_until_ms=opportunity.market.valid_until_ms,
                    notional_usdt=position.notional_usdt,
                    adv_fraction=float(quantity / Decimal(str(opportunity.market.adv_base))),
                    horizon_settlements=remaining,
                    **asdict(self.charges(event, opportunity)),
                )
            except ImpactModelError:
                estimate = None  # T1 emits exit; execution must still be available.
        decision = self.strategy.decide(
            now_ms=event.time_ms,
            forecast=forecast,
            costs=estimate,
            approval=opportunity.approval if opportunity else None,
            position=position,
        )
        if decision.action == "exit":
            self.trade(event, quantity, opening=False)
            self.position = None
        return decision

    def reserve(self, mark):
        reserve = abs(self.ledger.perp.quantity) * mark * self.config.collateral_fraction
        available = self.ledger.cash_usdt + self.ledger.perp.unrealized(mark)
        if available < reserve:
            raise ExecutionUnavailable("Collateral reserve shortfall; liquidation is not simulated")

    def admit(self, event):
        opportunity = event.opportunity
        if opportunity is None:
            return None
        market, curve = opportunity.market, opportunity.curve
        if (
            opportunity.fold_start_ms != fold_start(event.time_ms)
            or curve.evidence_end_exclusive_ms > opportunity.fold_start_ms
            or curve.admitted_at_ms > event.time_ms
            or curve.symbol != self.config.symbol
            or (curve.kind == "synthetic" and not self.config.policy.allow_synthetic_costs)
            or market.symbol != self.config.symbol
            or market.observed_at_ms > event.time_ms
            or event.time_ms >= market.valid_until_ms
            or market.adv_end_exclusive_ms != event.time_ms // DAY_MS * DAY_MS
            or not market.metadata_valid_from_ms <= event.time_ms < market.metadata_valid_until_ms
            or market.price_usdt != float(event.perp_mid)
        ):
            return None
        previous = self.fold_curves.setdefault(opportunity.fold_start_ms, curve.artifact_sha256)
        if previous != curve.artifact_sha256:
            raise ValueError("Impact artifact changed within a sealed monthly fold")
        return opportunity

    def charges(self, event, opportunity):
        perp_fee = float(self.fees.quote(self.config.symbol, "perp", event.time_ms)) * 10000
        spot_fee = float(self.fees.quote(self.config.symbol, "spot", event.time_ms)) * 10000
        hedge = (spot_fee + opportunity.spot_execution_bps) * float(event.spot_mid / event.perp_mid)
        return sizing.ExecutionCharges(
            opportunity.perp_half_spread_bps,
            opportunity.perp_half_spread_bps,
            perp_fee,
            perp_fee,
            hedge,
            hedge,
            opportunity.financing_fraction,
        )

    def trade(self, event, quantity, *, opening):
        # Inferred execution must use the same admitted curve as sizing/continuation.
        if self.config.execution_mode == "inferred" and self.admit(event) is None:
            raise ExecutionUnavailable("No admitted inferred exit execution")
        fills = self.executor.fills(event, quantity, opening=opening)
        expected = (
            ("spot", quantity if opening else -quantity),
            ("perp", -quantity if opening else quantity),
        )
        if len(fills) != 2 or any(
            (fill.market, fill.quantity, fill.time_ms, fill.symbol)
            != (market, amount, event.time_ms, self.config.symbol)
            or fill.reference_mid != (event.spot_mid if market == "spot" else event.perp_mid)
            for fill, (market, amount) in zip(fills, expected, strict=True)
        ):
            raise ExecutionUnavailable(
                "Executor must propose full paired fills at current time and reference mids"
            )
        proposed = self.ledger
        for fill in fills:
            proposed = proposed.fill(fill)
        reserve = abs(proposed.perp.quantity) * event.marks.perp * self.config.collateral_fraction
        available = proposed.cash_usdt + proposed.perp.unrealized(event.marks.perp)
        if opening and available < reserve:
            return False
        self.ledger = proposed
        return True

    def record(self, event, kind, decision, valuation, forecast, result):
        opportunity = event.opportunity if isinstance(event, MarketEvent) else None
        quantity = -self.ledger.perp.quantity
        return Record(
            event.event_id,
            event.time_ms,
            fold_start(event.time_ms),
            kind,
            decision,
            valuation,
            self.position.planned_settlements if self.position else None,
            self.position.settlements_held if self.position else 0,
            quantity,
            float(quantity / Decimal(str(opportunity.market.adv_base))) if opportunity else None,
            quantity * event.perp_mid if isinstance(event, MarketEvent) else None,
            opportunity.curve.artifact_sha256 if opportunity else None,
            opportunity.approval.evidence_sha256 if opportunity and opportunity.approval else None,
            {**forecast.prediction.summary(), "model_sha256": forecast.model_sha256}
            if forecast
            else None,
            self.config.execution_mode,
            self.ledger.cash_usdt,
            self.ledger.funding_usdt,
            self.admit(event) is not None if opportunity else False,
            asdict(result) if result else None,
        )


def iter_backtest(config: Config, events, fees: FeeSchedule, executor):
    """Yield scored records lazily. Errors preserve earlier records, never fabricate closure."""
    runner = _Runner(config, fees, executor)
    for event in events:
        with localcontext(Context(prec=60)):
            record = runner.process(event)
        if record is not None:
            yield record
