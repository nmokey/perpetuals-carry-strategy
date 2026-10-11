"""M7-T3: explicit inferred fills or market walks on copied C++ checkpoints."""

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from perpcarry.strategy.accounting import Fill


class ExecutionUnavailable(ValueError):
    """No admitted full paired execution; never interpret this as a successful close."""


def _fill(event, market, quantity, price):
    return Fill(
        f"{event.event_id}:{market}",
        event.marks.symbol,
        event.time_ms,
        market,
        quantity,
        price,
        event.spot_mid if market == "spot" else event.perp_mid,
    )


class InferredExecutor:
    mode = "inferred"

    def fills(self, event, quantity: Decimal, *, opening: bool):
        opportunity = event.opportunity
        if opportunity is None:
            raise ExecutionUnavailable("Missing impact inputs for inferred execution")
        curve, market = opportunity.curve, opportunity.market
        fraction = float(quantity / Decimal(str(market.adv_base)))
        if (
            curve.symbol != event.marks.symbol
            or curve.admitted_at_ms > event.time_ms
            or curve.evidence_end_exclusive_ms > event.time_ms
            or market.observed_at_ms > event.time_ms
            or event.time_ms >= market.valid_until_ms
            or not curve.size_min <= fraction <= curve.size_max
            or float(quantity) > market.validated_quantity_base
        ):
            raise ExecutionUnavailable(
                "Unsupported quantity or unavailable inferred execution inputs"
            )
        coefficient = curve.sell_coefficient_bps if opening else curve.buy_coefficient_bps
        # Keep the fitted coefficient's decimal representation; avoid a float sqrt round trip.
        size = quantity / Decimal(str(market.adv_base))
        perp_fraction = Decimal(str(coefficient)) * size.sqrt() / 10_000
        perp_fraction += Decimal(str(opportunity.perp_half_spread_bps)) / 10_000
        spot_fraction = Decimal(str(opportunity.spot_execution_bps)) / 10_000
        direction = Decimal(1 if opening else -1)
        return (
            _fill(
                event,
                "spot",
                direction * quantity,
                event.spot_mid * (1 + direction * spot_fraction),
            ),
            _fill(
                event,
                "perp",
                -direction * quantity,
                event.perp_mid * (1 - direction * perp_fraction),
            ),
        )


@dataclass(frozen=True)
class BookSnapshot:
    symbol: str
    time_ms: int
    book: Any  # A copied Pipeline checkpoint; importing this module needs no extension.


class BookExecutor:
    """Provider returns each market's copied consumer checkpoint at this decision time.

    Static counterfactual walks do not persist our footprint into later vendor updates.
    This backend does not manufacture snapshots, validate raw feeds, or admit their hashes.
    """

    mode = "book"

    def __init__(self, provider):
        self.provider = provider

    def fills(self, event, quantity: Decimal, *, opening: bool):
        import perpcarry_cpp as core

        fills = []
        for market, sign in (("spot", 1 if opening else -1), ("perp", -1 if opening else 1)):
            snapshot = self.provider(event.time_ms, market)
            if snapshot.symbol != event.marks.symbol or snapshot.time_ms != event.time_ms:
                raise ExecutionUnavailable("Book checkpoint time/symbol does not match execution")
            book = snapshot.book
            result = core.simulate_market_order(
                book, core.OrderSide.Buy if sign > 0 else core.OrderSide.Sell, float(quantity)
            )
            mid = event.spot_mid if market == "spot" else event.perp_mid
            if (
                result.exhausted_book
                or result.crossed_at_entry
                or result.beyond_validated_depth
                or not math.isclose(
                    result.filled_quantity, float(quantity), rel_tol=1e-12, abs_tol=0
                )
                or Decimal(str(result.mid_at_entry)) != mid
            ):
                raise ExecutionUnavailable("Invalid, partial or unvalidated book execution")
            fills.append(_fill(event, market, sign * quantity, Decimal(str(result.average_price))))
        return tuple(fills)
