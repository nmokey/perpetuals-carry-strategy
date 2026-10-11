"""M7-T3: actual model/sizing/ledger integration, deterministic prefixes and future poison."""

import datetime as dt
from dataclasses import replace

import pytest
from walk_forward_helpers import (
    END,
    START,
    STEP,
    WARMUP,
    D,
    observation,
    run,
    stream,
    tick,
    warmup,
)
from walk_forward_helpers import (
    scenario as scenario,
)

from perpcarry.ingestion.funding_series import utc_ms
from perpcarry.models.rolling_funding import DAY_MS
from perpcarry.strategy import costs
from perpcarry.strategy import walk_forward as wf
from perpcarry.strategy.accounting import Marks
from perpcarry.strategy.execution import (
    BookExecutor,
    BookSnapshot,
    ExecutionUnavailable,
    InferredExecutor,
)


def test_actual_model_entry_hold_original_horizon_funding_and_close(scenario):
    config, fees = scenario
    records = run(config, fees, stream(config, 3))
    markets = [r for r in records if r.event_type == "market"]
    assert [r.decision.action for r in markets] == ["enter", "hold", "exit"]
    assert markets[0].quantity_base == D(".9")
    assert markets[1].planned_settlements == 2 and markets[1].settlements_held == 1
    assert markets[2].quantity_base == 0 and markets[2].planned_settlements is None
    assert markets[2].decision.reason == "horizon_complete"
    # Opening: .9 spot at 100.02, -.9 perp at 99.994. Closing: 99.98 / 100.009.
    # Price costs .036 spot + .0135 perp = .0495; funding .9*100*.004*2=.72.
    assert markets[2].valuation.execution_cost_usdt == D(".0495")
    assert markets[2].valuation.funding_usdt == D(".72")
    assert markets[2].valuation.gross_pnl_usdt == D(".72")
    assert markets[2].valuation.net_pnl_usdt == D(".6705")
    assert markets[2].cash_usdt == D("10000.6705")
    assert markets[0].forecast["last_observation_time"] == START
    assert markets[0].evidence_admitted
    assert markets[0].impact_sha256 == "c" * 64
    assert all(r.time_ms >= START for r in records)  # Warmup never scored/traded.


def test_fixed_seed_is_exactly_reproducible(scenario):
    config, fees = scenario
    assert run(config, fees, stream(config)) == run(config, fees, stream(config))
    changed = run(replace(config, seed=704), fees, stream(config))
    original = run(config, fees, stream(config))
    assert changed[1].forecast["seed"] != original[1].forecast["seed"]


def test_future_funding_price_and_evidence_poison_cannot_change_prefix(scenario):
    config, fees = scenario
    events = stream(config)
    prefix = run(config, fees, events[: len(warmup()) + 4])
    future = events[len(warmup()) + 4 :]
    poisoned = []
    for event in future:
        if isinstance(event, wf.FundingEvent):
            poisoned.append(replace(event, rate=D("-.004"), mark_price=D(101)))
        else:
            poisoned.append(
                replace(
                    event,
                    spot_mid=D(99),
                    perp_mid=D(101),
                    marks=Marks(config.symbol, event.time_ms, D(98), D(102)),
                    opportunity=replace(
                        event.opportunity,
                        approval=replace(event.opportunity.approval, approved=False),
                        market=replace(event.opportunity.market, price_usdt=101.0),
                    ),
                )
            )
    result = run(config, fees, events[: len(warmup()) + 4] + poisoned)
    assert result[:4] == prefix
    assert result[-1].valuation != run(config, fees, events)[-1].valuation


def test_unread_corrupt_or_shuffled_future_preserves_already_yielded_records(scenario):
    config, fees = scenario
    events = stream(config)
    prefix_length = len(warmup()) + 4
    expected = run(config, fees, events[:prefix_length])
    touched = []

    def lazy():
        yield from events[:prefix_length]
        touched.append(True)
        raise ValueError("future payload is corrupt")

    iterator = wf.iter_backtest(config, lazy(), fees, InferredExecutor())
    assert [next(iterator) for _ in range(4)] == expected
    assert not touched
    with pytest.raises(ValueError, match="future payload"):
        next(iterator)
    shuffled = events[:prefix_length] + list(reversed(events[prefix_length:]))
    iterator = wf.iter_backtest(config, iter(shuffled), fees, InferredExecutor())
    assert [next(iterator) for _ in range(4)] == expected
    with pytest.raises(ValueError):
        list(iterator)


def test_truncation_does_not_force_liquidation_or_change_random_draws(scenario):
    config, fees = scenario
    full = run(config, fees, stream(config))
    truncated = run(config, fees, stream(config, 2))
    assert truncated == full[:4]
    assert truncated[-1].quantity_base == D(".9")
    assert truncated[-1].decision.action == "hold"


def test_missing_approval_waits_and_expired_approval_exits(scenario):
    config, fees = scenario
    events = stream(config, 2)
    first = events[len(warmup()) + 1]
    rejected = replace(
        first,
        opportunity=replace(
            first.opportunity, approval=replace(first.opportunity.approval, approved=False)
        ),
    )
    assert (
        run(config, fees, warmup() + [observation(START), rejected])[-1].decision.action == "wait"
    )
    last = events[-1]
    events[-1] = replace(
        last,
        opportunity=replace(
            last.opportunity,
            approval=replace(last.opportunity.approval, valid_until_ms=last.time_ms),
        ),
    )
    record = run(config, fees, events)[-1]
    assert record.decision.action == "exit" and record.quantity_base == 0


def test_missing_inferred_exit_does_not_fabricate_flat_position(scenario):
    config, fees = scenario
    events = stream(config, 2)
    events[-1] = replace(events[-1], opportunity=None)
    iterator = wf.iter_backtest(config, iter(events), fees, InferredExecutor())
    records = [next(iterator) for _ in range(3)]
    assert records[-1].quantity_base == D(".9")
    with pytest.raises(ExecutionUnavailable, match="inferred exit"):
        next(iterator)


def test_cash_and_mark_valued_collateral_bound_entry(scenario):
    config, fees = scenario
    config = replace(config, initial_capital_usdt=D(100))
    record = run(config, fees, stream(config, 1))[-1]
    assert record.quantity_base == D(".4")  # .5 lots would exhaust cash before costs/collateral.
    assert record.cash_usdt > D(40)
    assert record.valuation.net_equity_usdt == D("99.9904")


def test_reserve_shortfall_fails_without_invented_liquidation(scenario):
    config, fees = scenario
    events = stream(config, 1)
    events.append(
        replace(
            tick(config, START + 20000, decide=False),
            marks=Marks(config.symbol, START + 20000, D(100), D(10000)),
        )
    )
    with pytest.raises(ExecutionUnavailable, match="reserve shortfall"):
        run(config, fees, events)


@pytest.mark.parametrize("change", ["future", "fold", "adv", "metadata", "price", "synthetic"])
def test_inadmissible_market_evidence_cannot_open(scenario, change):
    config, fees = scenario
    event = tick(config, START + 16000)
    op = event.opportunity
    if change == "future":
        op = replace(op, curve=replace(op.curve, evidence_end_exclusive_ms=START + 1))
    elif change == "fold":
        op = replace(op, fold_start_ms=START + wf.HOUR_MS)
    elif change == "adv":
        op = replace(
            op,
            market=replace(
                op.market, adv_start_ms=WARMUP - DAY_MS, adv_end_exclusive_ms=START - DAY_MS
            ),
        )
    elif change == "metadata":
        op = replace(op, market=replace(op.market, metadata_valid_until_ms=event.time_ms))
    elif change == "price":
        op = replace(op, market=replace(op.market, price_usdt=101.0))
    else:
        config = replace(config, policy=replace(config.policy, allow_synthetic_costs=False))
    record = run(config, fees, warmup() + [observation(START), replace(event, opportunity=op)])[-1]
    assert record.decision.action == "wait" and record.quantity_base == 0
    assert not record.evidence_admitted


def test_fold_artifact_is_sealed_and_can_roll_at_next_month(scenario):
    config, fees = scenario
    events = stream(config, 2)
    events[-1] = replace(
        events[-1],
        opportunity=replace(
            events[-1].opportunity,
            curve=replace(events[-1].opportunity.curve, artifact_sha256="d" * 64),
        ),
    )
    with pytest.raises(ValueError, match="sealed"):
        run(config, fees, events)


@pytest.mark.parametrize("defect", ["gap", "cadence", "duplicate", "backwards", "unsettled"])
def test_bad_stream_events_fail_as_encountered(scenario, defect):
    config, fees = scenario
    events = stream(config, 1)
    if defect == "gap":
        events.pop(2)
    elif defect == "cadence":
        events[2] = replace(events[2], interval_hours=4)
    elif defect == "duplicate":
        events.append(events[-1])
    elif defect == "backwards":
        events[-1] = replace(events[-1], time_ms=START - 1)
    else:
        events = warmup() + [tick(config, START + 16000)]
    with pytest.raises(ValueError):
        run(config, fees, events)


def test_realized_financing_is_distinct_from_expected_charge(scenario):
    config, fees = scenario
    events = stream(config, 1)
    event = events[-1]
    events[-1] = replace(event, financing_usdt=D("1.25"))
    result = run(config, fees, events)[-1].valuation
    assert result.financing_usdt == D("1.25")
    assert result.net_pnl_usdt == result.gross_pnl_usdt - result.execution_cost_usdt - D("1.25")


def books(now, *, quantity=10.0, bid=99.0, ask=101.0):
    import perpcarry_cpp as core

    pipeline = core.Pipeline(queue_capacity=2)
    pipeline.run(
        [
            core.BookUpdate(
                timestamp=now, is_snapshot=True, side=core.Side.Bid, price=bid, quantity=quantity
            ),
            core.BookUpdate(
                timestamp=now, is_snapshot=True, side=core.Side.Ask, price=ask, quantity=quantity
            ),
        ]
    )
    return pipeline.replay_state().book()


def test_cpp_pipeline_book_execution_uses_full_copied_market_walks(scenario):
    config, fees = scenario
    config = replace(config, execution_mode="book")
    snapshots = {}

    def provider(now, market):
        snapshots.setdefault((now, market), books(now))
        return BookSnapshot(config.symbol, now, snapshots[now, market])

    records = run(config, fees, stream(config, 3), BookExecutor(provider))
    result = records[-1]
    assert result.quantity_base == 0
    assert result.valuation.execution_cost_usdt == D("3.6")
    assert result.valuation.gross_pnl_usdt == D(".72")
    assert result.valuation.net_pnl_usdt == D("-2.88")
    assert all(book.best_bid() == (99.0, 10.0) for book in snapshots.values())


@pytest.mark.parametrize("defect", ["partial", "future", "symbol", "crossed", "mid"])
def test_invalid_cpp_book_execution_has_no_paired_fill(scenario, defect):
    config, fees = scenario
    event = tick(config, START + 16000)
    book = books(
        event.time_ms,
        quantity=0.1 if defect == "partial" else 10.0,
        bid=102.0 if defect == "crossed" else 99.0,
        ask=98.0 if defect == "crossed" else (103.0 if defect == "mid" else 101.0),
    )
    snapshot = BookSnapshot(
        "SOLUSDT" if defect == "symbol" else config.symbol,
        event.time_ms + (1 if defect == "future" else 0),
        book,
    )
    with pytest.raises(ExecutionUnavailable):
        BookExecutor(lambda now, market: snapshot).fills(event, D(".9"), opening=True)


def test_backend_mode_mismatch_fails_before_events_are_read(scenario):
    config, fees = scenario
    with pytest.raises(ValueError, match="backend"):
        next(wf.iter_backtest(config, iter(()), fees, BookExecutor(None)))


def test_cpp_execution_cannot_claim_unvalidated_depth_as_admitted(scenario):
    import perpcarry_cpp as core

    config, _ = scenario
    event = tick(config, START + 16000)
    pipeline = core.Pipeline(queue_capacity=4)
    pipeline.run(
        [
            core.BookUpdate(
                timestamp=event.time_ms, is_snapshot=True, side=side, price=price, quantity=0.04
            )
            for i in range(26)
            for side, price in ((core.Side.Bid, 99 - i * 0.1), (core.Side.Ask, 101 + i * 0.1))
        ]
    )
    snapshot = BookSnapshot(config.symbol, event.time_ms, pipeline.replay_state().book())
    with pytest.raises(ExecutionUnavailable, match="unvalidated"):
        BookExecutor(lambda now, market: snapshot).fills(event, D("1.01"), opening=True)


def test_actual_m5_artifact_can_feed_the_integrated_loop(
    scenario, impact_artifact_factory, tmp_path
):
    from perpcarry.models import impact_model_io

    config, fees = scenario
    path = tmp_path / "synthetic-impact.json"
    impact_model_io.save(impact_artifact_factory(), path)
    events = stream(config, 3)
    for index, event in enumerate(events):
        if isinstance(event, wf.MarketEvent):
            curve = costs.load_curve(
                path,
                symbol=config.symbol,
                now_ms=event.time_ms,
                schedule="static",
                depth="inside_validated_depth",
                size_regime="all_sizes",
                allow_synthetic=True,
            )
            events[index] = replace(event, opportunity=replace(event.opportunity, curve=curve))
    records = run(config, fees, events)
    assert records[1].decision.action == "enter"
    assert records[-1].decision.action == "exit"
    assert records[1].impact_sha256 == records[-1].impact_sha256


def test_short_history_does_not_generate_a_funding_forecast(scenario):
    config, fees = scenario
    config = replace(config, min_settlements=1000)
    record = run(config, fees, stream(config, 1))[-1]
    assert record.forecast is None
    assert record.decision.reason == "funding_unavailable"
    assert record.quantity_base == 0


def test_monthly_roll_can_admit_a_different_prior_artifact(scenario):
    config, fees = scenario
    config = replace(config, end_ms=utc_ms(dt.date(2025, 12, 1)))
    fees = replace(fees, periods=tuple(replace(p, end_ms=config.end_ms) for p in fees.periods))
    events = warmup()
    for t in range(START, END + STEP, STEP):
        events.append(observation(t))
        event = tick(config, t + 16000)
        op = event.opportunity
        op = replace(
            op,
            approval=replace(op.approval, approved=False, valid_until_ms=config.end_ms),
            market=replace(op.market, metadata_valid_until_ms=config.end_ms),
        )
        if t == END:
            op = replace(
                op, curve=replace(op.curve, artifact_sha256="d" * 64, evidence_end_exclusive_ms=END)
            )
        events.append(replace(event, opportunity=op))
    records = run(config, fees, events)
    markets = [r for r in records if r.event_type == "market"]
    assert [markets[i].impact_sha256 for i in (0, -1)] == ["c" * 64, "d" * 64]
    assert [markets[i].fold_start_ms for i in (0, -1)] == [START, END]
    assert all(r.evidence_admitted for r in markets)


def test_decisions_inside_settlement_publication_guard_are_rejected(scenario):
    config, fees = scenario
    event = replace(
        tick(config, START + 16000),
        time_ms=START + 15000,
        marks=Marks(config.symbol, START + 15000, D(100), D(100)),
    )
    with pytest.raises(ValueError, match="availability"):
        run(config, fees, warmup() + [observation(START), event])


def test_proposed_book_fill_capital_failure_cannot_open_position(scenario):
    config, fees = scenario
    config = replace(config, execution_mode="book", initial_capital_usdt=D(100))

    def provider(now, market):
        return BookSnapshot(config.symbol, now, books(now, bid=1.0, ask=199.0))

    record = run(config, fees, stream(config, 1), BookExecutor(provider))[-1]
    assert record.decision.reason == "actual_fill_capital_unavailable"
    assert record.quantity_base == 0
    assert record.cash_usdt == D(100)


def test_executor_must_return_requested_pairs_before_any_ledger_trade(scenario):
    config, fees = scenario

    class Partial(InferredExecutor):
        def fills(self, event, quantity, *, opening):
            paired = super().fills(event, quantity, opening=opening)
            return (replace(paired[0], quantity=quantity / 2), paired[1])

    with pytest.raises(ExecutionUnavailable, match="full paired"):
        run(config, fees, stream(config, 1), Partial())


def test_executor_cannot_smuggle_future_reference_prices_into_gross_pnl(scenario):
    config, fees = scenario

    class FutureReference(InferredExecutor):
        def fills(self, event, quantity, *, opening):
            paired = super().fills(event, quantity, opening=opening)
            return (replace(paired[0], reference_mid=D(200)), paired[1])

    with pytest.raises(ExecutionUnavailable, match="reference mids"):
        run(config, fees, stream(config, 1), FutureReference())


@pytest.mark.parametrize("defect", ["missing", "late", "disabled"])
def test_missing_or_disabled_decision_calendar_cannot_be_a_successful_run(scenario, defect):
    config, fees = scenario
    events = stream(config, 2)
    if defect == "missing":
        events.pop(len(warmup()) + 1)
        # Stop at the next funding event: reject the missed decision immediately,
        # without relying on a later market event's independent calendar check.
        events = events[: len(warmup()) + 2]
    elif defect == "late":
        event = events[-1]
        events[-1] = replace(
            event, time_ms=event.time_ms + 1, marks=replace(event.marks, time_ms=event.time_ms + 1)
        )
    else:
        events[-1] = replace(events[-1], decide=False)
    with pytest.raises(ValueError, match="decision"):
        run(config, fees, events)


@pytest.mark.parametrize(
    "changes",
    [
        {"symbol": "0GUSDT"},
        {"start_ms": START + 1},
        {"end_ms": END + 1},
        {"collateral_fraction": D(0)},
        {"collateral_fraction": D("1.1")},
        {"initial_capital_usdt": D(0)},
        {"draws": True},
        {"min_settlements": 2},
        {"interval_hours": 7},
        {"seed": -1},
        {"execution_mode": "silent"},
    ],
)
def test_run_configuration_rejects_invalid_scope_and_parameters(scenario, changes):
    config, _ = scenario
    with pytest.raises(ValueError):
        replace(config, **changes)


def test_decision_fees_and_realized_fees_use_the_same_dated_schedule(scenario):
    config, fees = scenario
    fees = replace(
        fees,
        periods=tuple(
            replace(p, taker_fraction=D(".001") if p.market == "spot" else D(".0005"))
            for p in fees.periods
        ),
    )
    records = run(config, fees, stream(config, 3))
    assert records[1].decision.action == "enter"
    assert records[1].sizing["cost_estimate"]["entry_fraction"] == pytest.approx(
        0.00176, rel=0, abs=1e-18
    )
    assert records[-1].valuation.fees_usdt == D(".27000135")
    assert records[-1].valuation.net_pnl_usdt == D(".40049865")


def test_hedge_estimates_normalize_different_spot_and_perp_notionals(scenario):
    config, fees = scenario
    fees = replace(
        fees,
        periods=tuple(
            replace(p, taker_fraction=D(".001") if p.market == "spot" else D(".0005"))
            for p in fees.periods
        ),
    )
    events = [replace(event, rate=D(".00215")) for event in warmup()]
    events.extend([observation(START, rate=".00215"), tick(config, START + 16000, spot="200")])
    record = run(config, fees, events)[-1]
    assert record.decision.action == "wait" and record.quantity_base == 0


@pytest.mark.parametrize("quantity", [".01", "1"])
def test_inferred_fills_cannot_extrapolate_the_calibrated_size_range(scenario, quantity):
    config, _ = scenario
    with pytest.raises(ExecutionUnavailable, match="Unsupported"):
        InferredExecutor().fills(tick(config, START + 16000), D(quantity), opening=True)
