"""M1-T5 acceptance tests.

The offline fixture is 200 real rows from the Binance archive. It happens to be an
excellent test case for this task: 4 distinct prices spanning 0.1424-0.1427, so the GCD
lands on the correct 0.0001 *and* the window is far too thin to justify believing it.
Both halves are asserted -- getting the right answer for the wrong reason is precisely
what the confidence flag exists to catch.
"""

import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from perpcarry.ingestion.derive_symbol_meta import (
    MIN_DISTINCT_VALUES,
    TABLE_PATH,
    GridEstimate,
    SymbolMeta,
    SymbolMetaError,
    WindowEstimate,
    combine,
    decimal_gcd,
    estimate_grid,
    estimate_window,
    load_table,
    sample_days,
    save_table,
)

FIXTURE = Path(__file__).parent / "fixtures" / "0GUSDT-trades-2026-08-01.head.csv"
SYMBOL = "0GUSDT"


@pytest.fixture
def raw() -> pd.DataFrame:
    return pd.read_csv(FIXTURE, dtype=str)


def grid(value: str, distinct: int = MIN_DISTINCT_VALUES, offset: int = 0) -> GridEstimate:
    """A synthetic estimate whose observations really do sit on ``value``.

    ``offset`` shifts the observed range so two windows can be made to overlap or not --
    which is the whole question when pooling their evidence. Consecutive multiples, so
    the GCD of the set is exactly ``value``.
    """
    tick = Decimal(value)
    values = frozenset(tick * (offset + n) for n in range(1, distinct + 1))
    return GridEstimate(value=tick, values=values, samples=distinct)


def window(
    date: str, tick: str, step: str, distinct: int = MIN_DISTINCT_VALUES, offset: int = 0
) -> WindowEstimate:
    return WindowEstimate(
        symbol=SYMBOL,
        date=date,
        tick=grid(tick, distinct, offset),
        step=grid(step, distinct, offset),
    )


# --- Test 1: a known grid is recovered exactly -------------------------------------


@pytest.mark.parametrize(
    ("prices", "expected"),
    [
        # Consecutive multiples: the GCD of the *values* is the tick.
        (["0.1424", "0.1425", "0.1426", "0.1427"], "0.0001"),
        (["100.00", "100.50", "101.00"], "0.5"),
        (["3245.12", "3245.13", "3200.00"], "0.01"),
        (["5", "10", "15"], "5"),
        (["0.001", "0.002", "0.003"], "0.001"),
    ],
)
def test_known_grid_is_recovered_exactly(prices, expected):
    assert decimal_gcd(prices) == Decimal(expected)


def test_synthetic_trades_on_a_known_tick_grid_recover_that_tick():
    tick, step = Decimal("0.0001"), Decimal("0.001")
    prices = [format(Decimal("12.3456") + tick * n, "f") for n in range(50)]
    quantities = [format(step * n, "f") for n in range(1, 51)]
    frame = pd.DataFrame({"price": prices, "qty": quantities})

    estimate = estimate_window(frame, SYMBOL, "2026-08-01")

    assert estimate.tick.value == tick
    assert estimate.step.value == step


def test_the_scaling_exponent_is_the_maximum_not_the_minimum():
    """Pins the documented 100x bug.

    The first probe of this technique scaled by the *minimum* decimal exponent, which
    truncates the finer values and reports 0.0001 as 0.01 -- a plausible number, not an
    exception. With a min-based scale (1 place) 0.0001 truncates to 0 and the answer
    changes; this test fails if the choice is ever reverted.
    """
    assert decimal_gcd(["0.5", "0.25", "0.0001"]) == Decimal("0.0001")


@pytest.mark.parametrize(
    ("values", "expected_text"),
    [
        # Quantities arrive as "1.0"/"10.0", so the unnormalised result is 1.0.
        (["1.0", "10.0", "104.0"], "1"),
        (["0.0001", "0.0002"], "0.0001"),  # must not become 1E-4
        (["100", "200"], "100"),  # must not become 1E+2
    ],
)
def test_the_derived_value_is_canonical_text(values, expected_text):
    """Compares the *rendering*, not the value.

    ``Decimal("1.0") == Decimal("1")`` and ``Decimal("1E-4") == Decimal("0.0001")``, so
    no equality assertion can see the difference -- but this value is written into a
    committed file that is reviewed in diffs, and unstable rendering is diff noise on the
    one artifact whose job is to be stable.
    """
    assert format(decimal_gcd(values), "f") == expected_text


# --- Test 3: Decimal arithmetic throughout -----------------------------------------


def test_floats_are_rejected_rather_than_converted():
    with pytest.raises(TypeError, match="float"):
        decimal_gcd([0.1, 0.2, 0.3])


def test_values_a_float_implementation_would_get_wrong():
    """0.1/0.2/0.3 are not exactly representable in binary.

    A float-based implementation scales 0.3 to 2999999999999999.9 and returns a GCD with
    no relationship to the tick. Exact decimal arithmetic returns 0.1.
    """
    assert decimal_gcd([Decimal("0.1"), Decimal("0.2"), Decimal("0.3")]) == Decimal("0.1")


def test_a_long_price_is_not_rounded_by_the_decimal_context():
    """Scaling is done on the digit tuple, so context precision cannot truncate."""
    assert decimal_gcd(["12345.67890123", "12345.67890124"]) == Decimal("0.00000001")


def test_estimate_window_refuses_a_frame_already_cast_to_float():
    frame = pd.DataFrame({"price": [0.1424, 0.1425], "qty": [1.0, 2.0]})
    with pytest.raises(SymbolMetaError, match="dtype=str"):
        estimate_window(frame, SYMBOL, "2026-08-01")


# --- Test 4: a thin window is flagged, not silently trusted -------------------------


def test_a_thin_window_is_flagged_low_confidence():
    estimate = estimate_grid(["0.1424", "0.1425", "0.1426", "0.1427"])

    assert estimate.value == Decimal("0.0001")  # right answer...
    assert not estimate.confident  # ...but not enough evidence to believe it
    assert "Widen the window" in estimate.caveat


def test_a_rich_window_is_confident():
    prices = [format(Decimal("10") + Decimal("0.01") * n, "f") for n in range(MIN_DISTINCT_VALUES)]
    estimate = estimate_grid(prices)

    assert estimate.confident
    assert estimate.caveat is None


def test_the_overestimation_failure_mode_is_flagged():
    """The real risk: every observed price is an even multiple of the true tick.

    The GCD then returns 2x the truth with no error. Nothing can detect that from this
    data alone -- which is why it must be reported as low-confidence rather than
    returned as a fact.
    """
    estimate = estimate_grid(["0.10", "0.20", "0.30"])

    assert estimate.value == Decimal("0.1")  # true tick could be 0.01; unknowable here
    assert not estimate.confident


def test_a_single_window_is_caveated_even_when_rich():
    meta = combine([window("2026-08-01", "0.0001", "1", distinct=500)])

    assert not meta.confident
    assert any("single window" in c for c in meta.caveats)


def test_combine_is_confident_when_disjoint_rich_windows_agree():
    meta = combine(
        [
            window("2026-03-02", "0.0001", "1", distinct=321),
            window("2026-07-15", "0.0001", "1", distinct=371),
        ]
    )

    assert meta.confident
    assert meta.caveats == ()
    assert meta.tick_size == Decimal("0.0001")


def test_thin_windows_pool_their_evidence_when_they_observe_different_values():
    """Two thin days that saw *different* prices are jointly better evidence."""
    thin = MIN_DISTINCT_VALUES // 2
    meta = combine(
        [
            window("2026-01-01", "0.0001", "1", distinct=thin),
            window("2026-06-01", "0.0001", "1", distinct=thin, offset=thin),
        ]
    )

    assert meta.distinct_prices == 2 * thin
    assert meta.confident


def test_repeated_observations_are_not_counted_as_new_evidence():
    """The same prices seen on three days are one body of evidence, not three.

    Summing per-window distinct counts inflates confidence precisely where the windows
    overlap most -- which is where they are *least* independent, so the error runs in the
    dangerous direction. Three identical thin windows must stay low-confidence.
    """
    thin = MIN_DISTINCT_VALUES // 2
    identical = [window(d, "0.0001", "1", distinct=thin) for d in ("2026-01-01", "2026-06-01")]

    meta = combine(identical)

    assert meta.distinct_prices == thin  # not 2 * thin
    assert not meta.confident
    assert any("may be a multiple of the true grid" in c for c in meta.caveats)


def test_partially_overlapping_windows_count_the_union():
    thin = MIN_DISTINCT_VALUES // 2
    meta = combine(
        [
            window("2026-01-01", "0.0001", "1", distinct=thin),
            window("2026-06-01", "0.0001", "1", distinct=thin, offset=thin // 2),
        ]
    )

    assert meta.distinct_prices == thin + thin // 2


def test_a_value_written_two_ways_is_one_grid_point():
    """Deduplication is on the numeric value, not the text.

    An archive emitting both "1.0" and "1.00" would otherwise look like two distinct
    observations, inflating the evidence count by pure formatting.
    """
    estimate = estimate_grid(["1.0", "1.00", "1.000", "2.0"])

    assert estimate.distinct == 2
    assert estimate.samples == 4


# --- Test 2 (offline half): disagreement across windows is an error -----------------


def test_disagreeing_windows_are_an_error_not_a_silent_minimum():
    with pytest.raises(SymbolMetaError, match="re-ticked"):
        combine([window("2026-03-02", "0.0001", "1"), window("2026-07-15", "0.001", "1")])


def test_disagreement_names_both_windows_and_their_values():
    with pytest.raises(SymbolMetaError) as excinfo:
        combine([window("2026-03-02", "0.0001", "1"), window("2026-07-15", "0.001", "1")])

    message = str(excinfo.value)
    assert "2026-03-02=0.0001" in message and "2026-07-15=0.001" in message


def test_step_disagreement_is_caught_too():
    with pytest.raises(SymbolMetaError, match="step"):
        combine([window("2026-03-02", "0.0001", "1"), window("2026-07-15", "0.0001", "0.1")])


def test_windows_from_different_symbols_cannot_be_combined():
    other = WindowEstimate(symbol="ETHUSDT", date="2026-07-15", tick=grid("0.0001"), step=grid("1"))
    with pytest.raises(SymbolMetaError, match="different symbols"):
        combine([window("2026-03-02", "0.0001", "1"), other])


# --- The real-data fixture ----------------------------------------------------------


def test_real_fixture_recovers_the_verified_tick_and_step(raw):
    estimate = estimate_window(raw, SYMBOL, "2026-08-01")

    # Verified 2026-08-12 across three disjoint days (spec M1-T5).
    assert estimate.tick.value == Decimal("0.0001")
    assert estimate.step.value == Decimal("1")


def test_real_fixture_is_too_thin_to_be_confident(raw):
    """Guards the fixture as much as the code.

    4 distinct prices is below the threshold. If a future fixture were richer this would
    fail, which is the point: the thin-window assertions above would silently stop
    testing anything.
    """
    estimate = estimate_window(raw, SYMBOL, "2026-08-01")

    assert estimate.tick.distinct == 4
    assert not estimate.tick.confident
    assert estimate.step.distinct >= MIN_DISTINCT_VALUES  # quantities are plentiful


def test_real_fixture_sample_count_is_every_row(raw):
    estimate = estimate_window(raw, SYMBOL, "2026-08-01")
    assert estimate.tick.samples == len(raw) == 200


# --- Structural guards --------------------------------------------------------------


def test_empty_window_is_an_error():
    with pytest.raises(SymbolMetaError, match="no trades"):
        estimate_window(pd.DataFrame({"price": [], "qty": []}), SYMBOL, "2026-08-01")


def test_missing_columns_name_what_changed():
    with pytest.raises(SymbolMetaError, match=r"\['qty'\]"):
        estimate_window(pd.DataFrame({"price": ["1.0"]}), SYMBOL, "2026-08-01")


def test_a_zero_price_is_rejected_as_a_data_defect():
    with pytest.raises(SymbolMetaError, match="non-positive"):
        decimal_gcd(["0.0001", "0"])


def test_a_stray_header_row_is_named_rather_than_crashing_obscurely():
    with pytest.raises(SymbolMetaError, match="not a decimal value"):
        decimal_gcd(["0.0001", "price"])


def test_no_values_is_an_error():
    with pytest.raises(SymbolMetaError, match="no values"):
        decimal_gcd([])


def test_combine_rejects_no_windows():
    with pytest.raises(SymbolMetaError, match="no windows"):
        combine([])


# --- sample_days --------------------------------------------------------------------


def test_sample_days_spans_first_middle_and_last_month():
    days = sample_days(dt.date(2024, 9, 1), dt.date(2026, 8, 1))

    assert days[0] == dt.date(2024, 9, 1)
    assert days[-1] == dt.date(2026, 8, 1)
    assert len(days) == 3
    assert days[0] < days[1] < days[-1]


def test_sample_days_collapses_a_degenerate_range():
    assert sample_days(dt.date(2026, 8, 1), dt.date(2026, 8, 1)) == [dt.date(2026, 8, 1)]


def test_sample_days_rejects_a_reversed_range():
    with pytest.raises(SymbolMetaError, match="precedes"):
        sample_days(dt.date(2026, 8, 1), dt.date(2024, 9, 1))


# --- Test 5: the committed table round-trips ----------------------------------------


@pytest.fixture
def meta() -> SymbolMeta:
    return combine(
        [
            window("2026-03-02", "0.0001", "1", distinct=321),
            window("2026-07-15", "0.0001", "1", distinct=371),
        ],
        derived_on=dt.date(2026, 8, 20),
    )


def test_table_round_trips_exactly(tmp_path, meta):
    path = tmp_path / "symbol_meta.json"
    save_table({meta.symbol: meta}, path)

    assert load_table(path) == {meta.symbol: meta}


def test_table_stores_sizes_as_strings_not_json_numbers(tmp_path, meta):
    """A JSON number would put the value back through a float on every read."""
    path = tmp_path / "symbol_meta.json"
    save_table({meta.symbol: meta}, path)

    payload = json.loads(path.read_text())
    assert payload[SYMBOL]["tick_size"] == "0.0001"
    assert isinstance(payload[SYMBOL]["tick_size"], str)
    assert isinstance(payload[SYMBOL]["step_size"], str)


def test_loading_a_float_valued_table_is_refused(tmp_path):
    path = tmp_path / "symbol_meta.json"
    path.write_text(json.dumps({SYMBOL: {"symbol": SYMBOL, "tick_size": 0.0001}}))

    with pytest.raises(SymbolMetaError, match="already been through a float"):
        load_table(path)


def test_table_is_written_sorted_for_reviewable_diffs(tmp_path, meta):
    path = tmp_path / "symbol_meta.json"
    entries = {
        name: SymbolMeta(**{**meta.__dict__, "symbol": name}) for name in ("ZRXUSDT", "AAVEUSDT")
    }
    save_table(entries, path)

    assert list(json.loads(path.read_text())) == ["AAVEUSDT", "ZRXUSDT"]


def test_a_missing_table_reads_as_empty(tmp_path):
    assert load_table(tmp_path / "absent.json") == {}


def test_committed_table_is_loadable_and_internally_consistent():
    """The real committed table, not a fixture.

    Test 5's other half -- agreement with freshly derived values -- needs the archive and
    lives in the network test below.
    """
    table = load_table()

    for symbol, meta in table.items():
        assert meta.symbol == symbol
        assert meta.tick_size > 0 and meta.step_size > 0
        assert meta.confident, f"{symbol} was committed despite {meta.caveats}"
        assert len(meta.windows) >= 2, f"{symbol} lacks the cross-window stability check"


def test_committed_sizes_are_in_canonical_form():
    """Sizes are stored normalised and in plain notation.

    Numerically ``1.0 == 1`` and ``1E-4 == 0.0001``, so no value assertion can see this
    -- but the table is committed and read in diffs, and a step size that renders as
    "1.0" one run and "1" the next is diff noise on a file whose whole purpose is to be
    stable and reviewable.
    """
    payload = json.loads(TABLE_PATH.read_text())

    for symbol, entry in payload.items():
        for field in ("tick_size", "step_size"):
            text = entry[field]
            assert "E" not in text.upper(), f"{symbol}.{field} is in exponent notation: {text}"
            assert text == format(Decimal(text).normalize(), "f"), (
                f"{symbol}.{field} is not normalised: {text}"
            )


def test_the_committed_table_holds_the_spec_verified_values():
    """Pins the three symbols against the values M1-T5 verified by hand on 2026-08-12.

    0GUSDT and ETHUSDT are the spec's table; BTCUSDT is the symbol whose book data M2-M4
    replays. If a re-derivation ever moves one of these, that is a finding, not a
    refresh.
    """
    table = load_table()

    assert (table["0GUSDT"].tick_size, table["0GUSDT"].step_size) == (
        Decimal("0.0001"),
        Decimal("1"),
    )
    assert (table["ETHUSDT"].tick_size, table["ETHUSDT"].step_size) == (
        Decimal("0.01"),
        Decimal("0.001"),
    )
    assert (table["BTCUSDT"].tick_size, table["BTCUSDT"].step_size) == (
        Decimal("0.1"),
        Decimal("0.001"),
    )


# --- Test 2: two disjoint real windows agree (network) ------------------------------


@pytest.mark.network
def test_disjoint_real_windows_agree_and_match_the_committed_table():
    from perpcarry.ingestion.derive_symbol_meta import derive

    table = load_table()
    committed = table[SYMBOL]

    # Disjoint from each other and from the committed windows would be better still, but
    # these are the days the spec verified by hand.
    fresh = derive(SYMBOL, [dt.date(2026, 3, 2), dt.date(2026, 7, 15)])

    assert fresh.tick_size == committed.tick_size
    assert fresh.step_size == committed.step_size
    assert fresh.confident
