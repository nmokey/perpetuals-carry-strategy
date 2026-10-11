"""M7-T4: independently hand-reconciled fills, settlements and economic equity."""

from dataclasses import replace
from decimal import ROUND_UP, Decimal, localcontext
from pathlib import Path

import pytest

from perpcarry.strategy.accounting import (
    HOUR_MS,
    Fill,
    FundingSettlement,
    Ledger,
    Marks,
)
from perpcarry.strategy.fees import FeePeriod, FeeSchedule, load_schedule

D = Decimal
SYMBOL = "BTCUSDT"
FUND = 8 * HOUR_MS
SOURCE = "https://example.org/synthetic-fees"
REFERENCE = Path(__file__).resolve().parents[2] / "config/fee-reference.toml"


def schedule(*, spot="0.001", perp="0.0005", **kwargs):
    return FeeSchedule(
        tuple(
            FeePeriod(SYMBOL, market, 0, 100 * HOUR_MS, D(rate), SOURCE, 0, "assumption")
            for market, rate in (("spot", spot), ("perp", perp))
        ),
        allow_assumptions=True,
        **kwargs,
    )


def start():
    return Ledger.start(SYMBOL, D("10000"), FUND, schedule())


def fill(ledger, market, quantity, price, mid, *, time=1000, name=None):
    return ledger.fill(
        Fill(
            name or f"{market}-{time}-{quantity}",
            SYMBOL,
            time,
            market,
            D(quantity),
            D(price),
            D(mid),
        )
    )


def settle(ledger, rate="0.001", mark="110", *, hours=8, time=FUND, name="fund"):
    return ledger.settle(FundingSettlement(name, SYMBOL, time, hours, D(rate), D(mark)))


def value(ledger, spot="110", perp="112", *, time=None):
    return ledger.value(Marks(SYMBOL, ledger.time_ms if time is None else time, D(spot), D(perp)))


def test_hand_computed_round_trip_cash_gross_and_net():
    original = start()
    opened = fill(original, "spot", "2", "101", "100")
    opened = fill(opened, "perp", "-2", "99", "100")
    # Cash 10000 - 202 - .202 - .099; no fictitious 198 short-sale credit.
    assert original.cash_usdt == D("10000")
    assert opened.cash_usdt == D("9797.699")
    assert value(opened, "100", "100").net_pnl_usdt == D("-4.301")
    funded = settle(opened)  # 2 * 110 * .001 = .220, not entry notional * rate.
    assert funded.cash_usdt == D("9797.919")
    assert funded.funding_usdt == D(".220")
    marked = value(funded)  # spot +18; perp -26; total -8.
    assert marked.price_pnl_usdt == D("-8")
    assert marked.net_pnl_usdt == D("-8.081")
    assert marked.gross_pnl_usdt == D("-3.780")
    assert marked.net_equity_usdt == D("9991.919")
    closed = fill(funded, "spot", "-2", "109", "110", time=FUND + 16000)
    closed = fill(closed, "perp", "2", "113", "112", time=FUND + 16000)
    closed = closed.finance("financing", FUND + 17000, D(".5"))
    result = value(closed)
    # Actual price P&L +16 -28; reference price P&L +20 -24.
    # Fees .202 + .099 + .218 + .113 = .632; total execution cost 8.
    assert result.price_pnl_usdt == D("-12")
    assert result.fees_usdt == D(".632")
    assert result.execution_cost_usdt == D("8")
    assert result.gross_pnl_usdt == D("-3.780")
    assert result.net_pnl_usdt == D("-12.912")
    assert result.net_equity_usdt == result.cash_usdt == D("9987.088")
    assert result.gross_equity_usdt == D("9996.220")
    assert result.spot_quantity == result.perp_quantity == 0
    assert result.net_pnl_usdt == (
        result.gross_pnl_usdt
        - result.execution_cost_usdt
        - result.fees_usdt
        - result.financing_usdt
    )


def test_partial_unequal_legs_changing_funding_marks_and_negative_rates():
    ledger = fill(start(), "spot", "3", "100", "100")
    ledger = fill(ledger, "perp", "-2", "102", "102")
    ledger = settle(ledger, "0.002", "120", hours=4)
    assert ledger.funding_usdt == D(".480")
    ledger = fill(ledger, "perp", ".5", "110", "110", time=FUND + 16000)
    assert ledger.perp.quantity == D("-1.5")
    assert ledger.perp.basis_usdt == D("-153")
    assert ledger.perp.realized_usdt == D("-4")
    ledger = settle(ledger, "-.003", "90", time=12 * HOUR_MS, hours=1, name="negative")
    # Second payment -1.5 * 90 * .003 = -.405; summed funding .075.
    result = value(ledger, "105", "95")
    assert result.spot_quantity == D("3")
    assert result.perp_quantity == D("-1.5")
    assert result.funding_usdt == D(".075")
    assert result.price_pnl_usdt == D("21.5")  # 15 spot -4 realized +10.5 unrealized.
    assert result.fees_usdt == D(".4295")
    assert result.net_pnl_usdt == D("21.1455")
    assert result.net_equity_usdt == D("10021.1455")
    assert ledger.next_funding_ms == 13 * HOUR_MS


def test_weighted_basis_additions_and_partial_spot_exit():
    ledger = fill(start(), "spot", "1", "100", "100")
    ledger = fill(ledger, "spot", "2", "130", "130", time=2000)
    ledger = fill(ledger, "perp", "-1", "105", "105", time=2000)
    ledger = fill(ledger, "perp", "-2", "120", "120", time=3000)
    ledger = fill(ledger, "spot", "-1", "125", "125", time=4000)
    ledger = fill(ledger, "perp", "1", "110", "110", time=4000)
    assert ledger.spot.basis_usdt == D("240")
    assert ledger.spot.realized_usdt == D("5")
    assert ledger.perp.basis_usdt == D("-230")
    assert ledger.perp.realized_usdt == D("5")
    assert value(ledger, "125", "110").price_pnl_usdt == D("30")


@pytest.mark.parametrize("rate", ["-.01", "0", ".01"])
def test_flat_settlement_is_zero_with_no_commission(rate):
    ledger = settle(start(), rate)
    assert ledger.funding_usdt == ledger.fees_usdt == 0
    assert ledger.cash_usdt == D("10000")


def test_closed_before_settlement_receives_no_funding():
    ledger = fill(start(), "perp", "-2", "100", "100")
    ledger = fill(ledger, "perp", "2", "101", "101", time=FUND - 16000)
    assert settle(ledger).funding_usdt == 0


@pytest.mark.parametrize("offset", [-15000, -1, 0, 1, 15000])
def test_settlement_boundary_fills_are_rejected(offset):
    ledger = start() if offset < 0 else settle(start())
    before = ledger
    with pytest.raises(ValueError, match="settlement"):
        fill(ledger, "perp", "-1", "100", "100", time=FUND + offset)
    assert ledger == before


@pytest.mark.parametrize("offset", [-15001, 15001])
def test_outside_settlement_guard_fills_are_admitted(offset):
    ledger = start() if offset < 0 else settle(start())
    assert fill(ledger, "perp", "-1", "100", "100", time=FUND + offset).perp.quantity == -1


def test_missing_settlements_block_fills_marks_and_financing_even_flat():
    ledger = start()
    for action in (
        lambda: fill(ledger, "spot", "1", "100", "100", time=FUND),
        lambda: value(ledger, time=FUND),
        lambda: ledger.finance("cost", FUND, D(0)),
        lambda: settle(ledger, time=FUND + HOUR_MS),
    ):
        with pytest.raises(ValueError, match="[Mm]issing"):
            action()


def test_execution_improvement_is_signed_and_not_charged_twice():
    ledger = fill(start(), "spot", "1", "99", "100")
    ledger = fill(ledger, "perp", "-1", "101", "100")
    result = value(ledger, "100", "100")
    assert result.execution_cost_usdt == D("-2")
    assert result.gross_pnl_usdt == 0
    assert result.net_pnl_usdt == D("1.8505")


def test_fee_sensitivity_changes_net_but_not_gross_or_funding():
    outcomes = []
    for rate in ("0", ".001", ".002"):
        ledger = Ledger.start(SYMBOL, D(1000), FUND, schedule(spot=rate, perp=rate))
        ledger = fill(ledger, "spot", "1", "100", "100")
        ledger = fill(ledger, "perp", "-1", "100", "100")
        ledger = settle(ledger)
        ledger = fill(ledger, "spot", "-1", "110", "110", time=FUND + 16000)
        ledger = fill(ledger, "perp", "1", "110", "110", time=FUND + 16000)
        outcomes.append(value(ledger))
    assert [v.net_pnl_usdt for v in outcomes] == [D(".11"), D("-.31"), D("-.73")]
    assert all(v.gross_pnl_usdt == v.funding_usdt == D(".11") for v in outcomes)


def test_insufficient_cash_is_reported_without_inventing_financing():
    ledger = Ledger.start(SYMBOL, D("50"), FUND, schedule())
    ledger = fill(ledger, "spot", "1", "100", "100")
    result = value(ledger, "100", "100")
    assert result.cash_usdt == D("-50.1")
    assert result.financing_usdt == 0
    assert result.net_equity_usdt == D("49.9")


def test_decimal_results_are_independent_of_ambient_precision():
    def calculate():
        ledger = fill(start(), "spot", ".123456789", "1234.56789", "1234")
        ledger = fill(ledger, "perp", "-.123456789", "1234.56789", "1234")
        return value(settle(ledger, ".000123456789", "1345.6789"))

    expected = calculate()
    with localcontext() as context:
        context.prec = 6
        context.rounding = ROUND_UP
        assert calculate() == expected


@pytest.mark.parametrize(
    "changes",
    [
        {"event_id": ""},
        {"event_id": 1},
        {"symbol": "SOLUSDT"},
        {"time_ms": -1},
        {"time_ms": True},
        {"market": "other"},
        {"quantity": D(0)},
        {"quantity": D("NaN")},
        {"quantity": 1.0},
        {"price": D(0)},
        {"price": D("Infinity")},
        {"reference_mid": D("-1")},
        {"market": "perp", "quantity": D(1)},
        {"quantity": D(-1)},
    ],
)
def test_bad_fills_reject_without_mutation(changes):
    ledger = start()
    event = Fill("fill", SYMBOL, 1000, "spot", D(1), D(100), D(100))
    with pytest.raises(ValueError):
        ledger.fill(replace(event, **changes))
    assert ledger == start()


def test_duplicate_backwards_and_oversize_closes_are_rejected():
    event = Fill("entry", SYMBOL, 2000, "spot", D(1), D(100), D(100))
    ledger = start().fill(event)
    with pytest.raises(ValueError, match="Duplicate"):
        ledger.fill(event)
    with pytest.raises(ValueError, match="backwards"):
        ledger.fill(replace(event, event_id="earlier", time_ms=1999))
    with pytest.raises(ValueError, match="reverses"):
        fill(ledger, "spot", "-2", "100", "100", time=3000)
    ledger = fill(ledger, "perp", "-1", "100", "100", time=3000)
    with pytest.raises(ValueError, match="reverses"):
        fill(ledger, "perp", "2", "100", "100", time=4000)
    funded = settle(ledger)
    with pytest.raises(ValueError, match="Duplicate"):
        settle(funded)


@pytest.mark.parametrize(
    "changes",
    [
        {"time_ms": FUND + 1},
        {"symbol": "SOLUSDT"},
        {"interval_hours": 0},
        {"interval_hours": 25},
        {"interval_hours": True},
        {"rate": D("NaN")},
        {"mark_price": D(0)},
        {"mark_price": D("Infinity")},
    ],
)
def test_bad_funding_rows_reject_without_mutation(changes):
    ledger = start()
    event = FundingSettlement("fund", SYMBOL, FUND, 8, D(".001"), D(110))
    with pytest.raises(ValueError):
        ledger.settle(replace(event, **changes))
    assert ledger == start()


@pytest.mark.parametrize(
    "changes",
    [{"symbol": "SOLUSDT"}, {"time_ms": 999}, {"spot": D(0)}, {"perp": D("NaN")}],
)
def test_bad_valuation_marks_are_rejected(changes):
    ledger = fill(start(), "spot", "1", "100", "100")
    with pytest.raises(ValueError):
        ledger.value(replace(Marks(SYMBOL, 1000, D(100), D(100)), **changes))


def test_financing_requires_explicit_finite_nonnegative_charges_and_unique_ids():
    ledger = start().finance("charge", 1000, D("1.25"))
    assert ledger.cash_usdt == D("9998.75")
    for name, time, charge in (
        ("charge", 1000, D(1)),
        ("negative", 2000, D(-1)),
        ("nan", 2000, D("NaN")),
        ("past", 999, D(1)),
    ):
        with pytest.raises(ValueError):
            ledger.finance(name, time, charge)


@pytest.mark.parametrize("market", ["spot", "perp"])
def test_dated_fee_changes_apply_to_actual_entry_and_exit_fills(market):
    first = FeePeriod(SYMBOL, market, 0, 2000, D(".001"), SOURCE, 0, "verified")
    second = replace(first, start_ms=2000, end_ms=10000, taker_fraction=D(".002"))
    fees = FeeSchedule((first, second))
    ledger = Ledger.start(SYMBOL, D(1000), FUND, fees)
    quantity = "1" if market == "spot" else "-1"
    ledger = fill(ledger, market, quantity, "100", "100")
    ledger = fill(ledger, market, str(-D(quantity)), "120", "120", time=2000)
    assert ledger.fees_usdt == D(".34")
    assert fees.quote(SYMBOL, market, 1999) == D(".001")
    assert fees.quote(SYMBOL, market, 2000) == D(".002")
    with pytest.raises(ValueError, match="coverage"):
        fees.quote(SYMBOL, market, 10000)


def test_reference_fees_are_cited_assumptions_requiring_opt_in():
    fees = load_schedule(REFERENCE)
    assert not fees.allow_assumptions
    assert len(fees.periods) == 4
    for period in fees.periods:
        assert period.kind == "assumption"
        assert period.source.startswith("https://www.binance.com/")
        assert period.observed_at_ms == 1791590400000
        with pytest.raises(ValueError, match="explicit admission"):
            fees.quote(period.symbol, period.market, period.start_ms)
        admitted = load_schedule(REFERENCE, allow_assumptions=True)
        expected = D(".001") if period.market == "spot" else D(".0005")
        assert admitted.quote(period.symbol, period.market, period.start_ms) == expected


def test_fee_schedule_has_no_missing_scope_future_or_overlap_fallback():
    first = FeePeriod(SYMBOL, "spot", 1000, 2000, D(".001"), SOURCE, 1500, "verified")
    fees = FeeSchedule((first,))
    for symbol, market, time in (
        ("SOLUSDT", "spot", 1500),
        (SYMBOL, "perp", 1500),
        (SYMBOL, "spot", 999),
        (SYMBOL, "spot", 2000),
    ):
        with pytest.raises(ValueError, match="coverage"):
            fees.quote(symbol, market, time)
    with pytest.raises(ValueError, match="future"):
        fees.quote(SYMBOL, "spot", 1499)
    with pytest.raises(ValueError, match="Overlapping"):
        FeeSchedule((first, replace(first, start_ms=1999, end_ms=3000)))
    assert FeeSchedule((first, replace(first, start_ms=2000, end_ms=3000)))


@pytest.mark.parametrize(
    "changes",
    [
        {"start_ms": -1},
        {"end_ms": 0},
        {"observed_at_ms": True},
        {"market": "other"},
        {"symbol": ""},
        {"taker_fraction": D(-1)},
        {"taker_fraction": D(1)},
        {"taker_fraction": D("NaN")},
        {"source": ""},
        {"kind": "unknown"},
    ],
)
def test_fee_provenance_validation(changes):
    period = FeePeriod(SYMBOL, "spot", 0, 2000, D(".001"), SOURCE, 0, "verified")
    with pytest.raises(ValueError):
        replace(period, **changes)


def test_bad_ledger_initialization():
    for symbol, capital, boundary, fees in (
        ("", D(1), FUND, schedule()),
        (SYMBOL, D(0), FUND, schedule()),
        (SYMBOL, D("NaN"), FUND, schedule()),
        (SYMBOL, D(1), FUND + 1, schedule()),
        (SYMBOL, D(1), FUND, None),
    ):
        with pytest.raises(ValueError):
            Ledger.start(symbol, capital, boundary, fees)


@pytest.mark.parametrize(
    "content",
    [
        "schema_version = true",
        "schema_version = 2",
        "schema_version = 1",
        "schema_version = 1\nperiods = {}",
        'schema_version = 1\nperiods = ["bad"]',
    ],
)
def test_bad_fee_file_schema_is_rejected(tmp_path, content):
    path = tmp_path / "fees.toml"
    path.write_text(content)
    with pytest.raises(ValueError):
        load_schedule(path)


def test_fee_file_rejects_binary_float_rates(tmp_path):
    path = tmp_path / "fees.toml"
    path.write_text(
        REFERENCE.read_text().replace('taker_fraction = "0.0005"', "taker_fraction = 0.0005")
    )
    with pytest.raises(ValueError, match="decimal strings"):
        load_schedule(path, allow_assumptions=True)


def test_schedule_requires_immutable_periods_and_boolean_admission():
    period = schedule().periods[0]
    for periods, admission in (
        ([], False),
        ([period], False),
        ((), False),
        ((period,), 1),
        ((None,), False),
    ):
        with pytest.raises(ValueError):
            FeeSchedule(periods, admission)


@pytest.mark.parametrize("version", ["true", "2"])
def test_fee_schema_version_rejection_is_not_hidden_by_invalid_periods(tmp_path, version):
    path = tmp_path / "fees.toml"
    path.write_text(
        REFERENCE.read_text().replace("schema_version = 1", f"schema_version = {version}")
    )
    with pytest.raises(ValueError, match="schema"):
        load_schedule(path)
