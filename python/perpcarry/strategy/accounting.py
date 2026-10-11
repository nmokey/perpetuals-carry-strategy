"""M7-T4: immutable long-spot/short-linear-perp economic cash accounting.

Fees are explicit USDT equivalents. This does not reserve derivative margin or model
liquidation, fee-token inventory or base-asset commission deductions (see task spec).
"""

from dataclasses import dataclass, replace
from decimal import Context, Decimal, localcontext

from perpcarry.strategy.fees import FeeSchedule, Market, decimal, timestamp

ZERO = Decimal(0)
HOUR_MS = 3_600_000
SETTLEMENT_GUARD_MS = 15_000


@dataclass(frozen=True)
class Fill:
    event_id: str
    symbol: str
    time_ms: int
    market: Market
    quantity: Decimal  # Signed actually executed base quantity, not the requested order.
    price: Decimal
    reference_mid: Decimal


@dataclass(frozen=True)
class FundingSettlement:
    event_id: str
    symbol: str
    time_ms: int  # Nominal UTC boundary, not the archive's jittered timestamp.
    interval_hours: int
    rate: Decimal
    mark_price: Decimal


@dataclass(frozen=True)
class Marks:
    symbol: str
    time_ms: int
    spot: Decimal
    perp: Decimal


@dataclass(frozen=True)
class Leg:
    quantity: Decimal = ZERO
    basis_usdt: Decimal = ZERO  # Signed remaining cost basis.
    realized_usdt: Decimal = ZERO

    def trade(self, quantity: Decimal, price: Decimal) -> tuple["Leg", Decimal]:
        closing = self.quantity * quantity < 0
        if closing:
            average = self.basis_usdt / self.quantity
            realized = -quantity * (price - average)
            basis = (self.quantity + quantity) * average
        else:
            realized = ZERO
            basis = self.basis_usdt + quantity * price
        return Leg(self.quantity + quantity, basis, self.realized_usdt + realized), realized

    def unrealized(self, mark: Decimal) -> Decimal:
        return self.quantity * mark - self.basis_usdt


@dataclass(frozen=True)
class Valuation:
    time_ms: int
    cash_usdt: Decimal
    spot_quantity: Decimal
    perp_quantity: Decimal
    price_pnl_usdt: Decimal
    funding_usdt: Decimal
    fees_usdt: Decimal
    financing_usdt: Decimal
    execution_cost_usdt: Decimal
    gross_pnl_usdt: Decimal
    net_pnl_usdt: Decimal
    gross_equity_usdt: Decimal
    net_equity_usdt: Decimal


@dataclass(frozen=True)
class Ledger:
    symbol: str
    initial_capital_usdt: Decimal
    next_funding_ms: int
    fees: FeeSchedule
    cash_usdt: Decimal
    time_ms: int = 0
    spot: Leg = Leg()
    perp: Leg = Leg()
    funding_usdt: Decimal = ZERO
    fees_usdt: Decimal = ZERO
    financing_usdt: Decimal = ZERO
    execution_cost_usdt: Decimal = ZERO
    last_funding_ms: int | None = None
    event_ids: frozenset[str] = frozenset()

    @classmethod
    def start(
        cls, symbol: str, initial_capital_usdt: Decimal, next_funding_ms: int, fees: FeeSchedule
    ) -> "Ledger":
        decimal(initial_capital_usdt, "initial_capital_usdt", positive=True)
        timestamp(next_funding_ms, "next_funding_ms")
        if (
            not isinstance(symbol, str)
            or not symbol
            or not isinstance(fees, FeeSchedule)
            or next_funding_ms % HOUR_MS
        ):
            raise ValueError("Require symbol, explicit fees and nominal hourly funding boundary")
        return cls(symbol, initial_capital_usdt, next_funding_ms, fees, initial_capital_usdt)

    def _event(self, event_id: str, symbol: str, time_ms: int):
        timestamp(time_ms, "time_ms")
        if (
            not isinstance(event_id, str)
            or not event_id
            or event_id in self.event_ids
            or symbol != self.symbol
            or time_ms < self.time_ms
        ):
            raise ValueError("Duplicate, backwards or out-of-scope accounting event")

    def fill(self, event: Fill) -> "Ledger":
        self._event(event.event_id, event.symbol, event.time_ms)
        decimal(event.quantity, "quantity")
        decimal(event.price, "price", positive=True)
        decimal(event.reference_mid, "reference_mid", positive=True)
        if event.market not in ("spot", "perp") or event.quantity == 0:
            raise ValueError("Require nonzero actual spot/perp fill")
        if event.time_ms >= self.next_funding_ms:
            raise ValueError("Missing funding settlement before fill")
        if event.market == "perp" and (
            self.next_funding_ms - event.time_ms <= SETTLEMENT_GUARD_MS
            or (
                self.last_funding_ms is not None
                and event.time_ms - self.last_funding_ms <= SETTLEMENT_GUARD_MS
            )
        ):
            raise ValueError("Perp fill has ambiguous settlement eligibility")
        leg = self.spot if event.market == "spot" else self.perp
        with localcontext(Context(prec=50)):
            updated, realized = leg.trade(event.quantity, event.price)
            if (event.market == "spot" and updated.quantity < 0) or (
                event.market == "perp" and updated.quantity > 0
            ):
                raise ValueError("Fill reverses the allowed carry leg")
            fee = (
                abs(event.quantity)
                * event.price
                * self.fees.quote(self.symbol, event.market, event.time_ms)
            )
            cash_change = -event.quantity * event.price if event.market == "spot" else realized
            return replace(
                self,
                **{event.market: updated},
                cash_usdt=self.cash_usdt + cash_change - fee,
                fees_usdt=self.fees_usdt + fee,
                execution_cost_usdt=self.execution_cost_usdt
                + event.quantity * (event.price - event.reference_mid),
                time_ms=event.time_ms,
                event_ids=self.event_ids | {event.event_id},
            )

    def settle(self, event: FundingSettlement) -> "Ledger":
        self._event(event.event_id, event.symbol, event.time_ms)
        decimal(event.rate, "rate")
        decimal(event.mark_price, "mark_price", positive=True)
        if (
            event.time_ms != self.next_funding_ms
            or type(event.interval_hours) is not int
            or not 1 <= event.interval_hours <= 24
        ):
            raise ValueError("Missing/misaligned settlement or invalid per-row interval")
        with localcontext(Context(prec=50)):
            payment = -self.perp.quantity * event.mark_price * event.rate
            return replace(
                self,
                cash_usdt=self.cash_usdt + payment,
                funding_usdt=self.funding_usdt + payment,
                next_funding_ms=event.time_ms + event.interval_hours * HOUR_MS,
                last_funding_ms=event.time_ms,
                time_ms=event.time_ms,
                event_ids=self.event_ids | {event.event_id},
            )

    def finance(self, event_id: str, time_ms: int, cost_usdt: Decimal) -> "Ledger":
        """Record an explicit realized financing charge; never accrue an assumed rate."""
        self._event(event_id, self.symbol, time_ms)
        decimal(cost_usdt, "cost_usdt")
        if cost_usdt < 0 or time_ms >= self.next_funding_ms:
            raise ValueError("Negative financing or missing funding settlement")
        with localcontext(Context(prec=50)):
            return replace(
                self,
                cash_usdt=self.cash_usdt - cost_usdt,
                financing_usdt=self.financing_usdt + cost_usdt,
                time_ms=time_ms,
                event_ids=self.event_ids | {event_id},
            )

    def value(self, marks: Marks) -> Valuation:
        timestamp(marks.time_ms, "time_ms")
        decimal(marks.spot, "spot mark", positive=True)
        decimal(marks.perp, "perp mark", positive=True)
        if (
            marks.symbol != self.symbol
            or marks.time_ms < self.time_ms
            or marks.time_ms >= self.next_funding_ms
        ):
            raise ValueError("Backwards/out-of-scope marks or missing funding settlement")
        with localcontext(Context(prec=50)):
            price_pnl = (
                self.spot.realized_usdt
                + self.spot.unrealized(marks.spot)
                + self.perp.realized_usdt
                + self.perp.unrealized(marks.perp)
            )
            equity = (
                self.cash_usdt + self.spot.quantity * marks.spot + self.perp.unrealized(marks.perp)
            )
            net = equity - self.initial_capital_usdt
            gross = price_pnl + self.funding_usdt + self.execution_cost_usdt
            return Valuation(
                marks.time_ms,
                self.cash_usdt,
                self.spot.quantity,
                self.perp.quantity,
                price_pnl,
                self.funding_usdt,
                self.fees_usdt,
                self.financing_usdt,
                self.execution_cost_usdt,
                gross,
                net,
                self.initial_capital_usdt + gross,
                equity,
            )
