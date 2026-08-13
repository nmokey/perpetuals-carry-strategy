"""M1-T2 acceptance tests.

Both fixtures are real archive months, chosen to cover the two cases that matter:
``BTCUSDT`` 2026-06 is a clean 8h month, and ``1000BONKUSDT`` 2026-06 is a 4h month with a
**genuine upstream gap** -- 179 settlements where 180 are expected, an 8h hole after
2026-06-24 00:00 UTC. Real data beats a synthesised gap here: it is the actual shape the
validator has to handle.
"""

import datetime as dt
import io
import zipfile
from pathlib import Path

import httpx
import pandas as pd
import pytest

from perpcarry.ingestion.download import ChecksumMismatch, DownloadError
from perpcarry.ingestion.fetch_funding import (
    MS_PER_HOUR,
    RATE_SANITY_BOUND,
    SCHEMA,
    FundingDataError,
    backfill,
    check_month,
    expected_settlements,
    fetch_month,
    implausible_rates,
    interval_changes,
    normalise,
    settlement_gaps,
    store,
)
from perpcarry.storage import read_parquet

FIXTURES = Path(__file__).parent / "fixtures"
BTC = "BTCUSDT"
BONK = "1000BONKUSDT"
JUNE = dt.date(2026, 6, 1)


def load(symbol: str) -> pd.DataFrame:
    return pd.read_csv(FIXTURES / f"{symbol}-fundingRate-2026-06.csv", dtype=str)


@pytest.fixture
def btc_raw() -> pd.DataFrame:
    return load(BTC)


@pytest.fixture
def btc(btc_raw) -> pd.DataFrame:
    return normalise(btc_raw, BTC)


@pytest.fixture
def bonk() -> pd.DataFrame:
    return normalise(load(BONK), BONK)


def zipped(csv_bytes: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("f.csv", csv_bytes)
    return buf.getvalue()


def archive_client(csv_bytes: bytes, *, checksum: str | None = None) -> httpx.Client:
    payload = zipped(csv_bytes)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".CHECKSUM"):
            return (
                httpx.Response(200, text=f"{checksum}  f.zip\n")
                if checksum
                else httpx.Response(404)
            )
        return httpx.Response(200, content=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


# --- schema (criterion 5) -----------------------------------------------------


def test_output_matches_section_3_3_schema(btc):
    assert list(btc.columns) == list(SCHEMA)
    assert {c: str(d) for c, d in btc.dtypes.items()} == SCHEMA


def test_mark_price_is_absent_not_null(btc):
    """Section 3.3 dropped it deliberately; emitting a null column would be worse."""
    assert "mark_price" not in btc.columns


def test_funding_interval_hours_is_carried_through(btc, bonk):
    """The column Section 3.3 gained -- and the reason nothing may assume 8h."""
    assert set(btc["funding_interval_hours"]) == {8}
    assert set(bonk["funding_interval_hours"]) == {4}


def test_schema_drift_is_rejected(btc_raw):
    with pytest.raises(FundingDataError, match="missing columns"):
        normalise(btc_raw.drop(columns=["last_funding_rate"]), BTC)


# --- settlement cadence (criteria 1, 2) ---------------------------------------


def test_a_clean_month_has_no_gaps(btc):
    """The ~1 ms jitter must not read as a gap -- naive hour differencing says it does."""
    assert settlement_gaps(btc) == []


def test_the_fixture_really_does_jitter(btc_raw):
    """Guards the guard: if the source stopped jittering, the tolerance is untested."""
    times = sorted(int(t) for t in btc_raw["calc_time"])
    diffs = {times[i + 1] - times[i] for i in range(len(times) - 1)}

    assert len(diffs) > 1, "fixture no longer exercises the jitter tolerance"
    assert all(abs(d - 8 * MS_PER_HOUR) < 5_000 for d in diffs)


def test_expected_settlement_count(btc, bonk):
    assert expected_settlements(JUNE, 8) == 90 == len(btc)
    assert expected_settlements(JUNE, 4) == 180
    assert len(bonk) == 179, "fixture should carry the real upstream gap"


def test_expected_count_uses_real_month_lengths():
    assert expected_settlements(dt.date(2026, 2, 1), 8) == 84  # 28 days
    assert expected_settlements(dt.date(2024, 2, 1), 8) == 87  # leap year, 29 days
    assert expected_settlements(dt.date(2026, 1, 1), 4) == 186


# --- gap detection (criterion 3) ----------------------------------------------


def test_the_real_upstream_gap_is_found_and_located(bonk):
    gaps = settlement_gaps(bonk)

    assert len(gaps) == 1
    _, expected_at, missing = gaps[0]
    assert missing == 1
    when = dt.datetime.fromtimestamp(expected_at / 1000, dt.UTC)
    assert (when.date(), when.hour) == (dt.date(2026, 6, 24), 4)


def test_check_month_reports_the_missing_settlement_time(bonk):
    with pytest.raises(FundingDataError, match=r"2026-06-24 04:00 UTC"):
        check_month(bonk, BONK, JUNE)


def test_a_removed_settlement_is_detected(btc):
    punched = btc.drop(index=10).reset_index(drop=True)

    gaps = settlement_gaps(punched)

    assert len(gaps) == 1
    assert gaps[0][2] == 1


def test_consecutive_missing_settlements_are_counted(btc):
    punched = btc.drop(index=[10, 11]).reset_index(drop=True)

    assert settlement_gaps(punched)[0][2] == 2


def test_clean_month_passes_every_check(btc):
    check_month(btc, BTC, JUNE)  # must not raise


# --- interval changes ---------------------------------------------------------


def recadenced(first: int = 8, second: int = 4) -> pd.DataFrame:
    """Settlements at one cadence that switch to another, timestamps matching each.

    Built by hand rather than by relabelling a real month: setting the interval column to
    4 while leaving 8h-spaced timestamps describes data that cannot exist, and the code is
    right to call that a gap.
    """
    intervals = [first] * 10 + [second] * 10
    # A row's interval describes the period that just ended, so each step is spaced by the
    # *later* row's cadence -- including the step across the change itself.
    times, t = [1_780_272_000_000], 1_780_272_000_000
    for interval in intervals[1:]:
        t += interval * MS_PER_HOUR
        times.append(t)
    return pd.DataFrame(
        {
            "funding_time": pd.array(times, dtype="int64"),
            "symbol": pd.array(["X"] * len(times), dtype="string"),
            "funding_rate": [0.0001] * len(times),
            "funding_interval_hours": pd.array(intervals, dtype="int64"),
            "date": pd.array(["2026-06-01"] * len(times), dtype="string"),
        }
    )


def test_an_interval_change_is_reported_separately_from_a_gap():
    """A re-cadenced symbol is a different fact from lost data."""
    changed = recadenced()

    assert settlement_gaps(changed) == [], "a cadence change is not a missing settlement"
    changes = interval_changes(changed)
    assert len(changes) == 1
    assert changes[0][1:] == (8, 4)


def test_a_gap_after_a_recadence_is_still_found():
    """A cadence change must not mask a genuine gap later in the same month."""
    changed = recadenced().drop(index=15).reset_index(drop=True)

    assert len(settlement_gaps(changed)) == 1


def test_a_slowing_recadence_is_not_mistaken_for_a_gap():
    """4h -> 8h is the direction that gets this wrong if the earlier row's interval is used.

    The step across the change is 8h. Measured against the *earlier* row (4h) it looks like
    a missing settlement; measured against the later row (8h), which is the cadence that
    period actually settled under, it is correct.
    """
    frame = recadenced(first=4, second=8)

    assert settlement_gaps(frame) == [], "the 8h step across the change is not a gap"
    assert [c[1:] for c in interval_changes(frame)] == [(4, 8)]


# --- plausibility (criterion 4) -----------------------------------------------


def test_real_rates_are_plausible(btc, bonk):
    assert implausible_rates(btc).empty
    assert implausible_rates(bonk).empty


def test_absurd_and_nonfinite_rates_are_flagged(btc):
    corrupted = btc.copy()
    corrupted.loc[3, "funding_rate"] = 12.0
    corrupted.loc[4, "funding_rate"] = float("nan")

    assert len(implausible_rates(corrupted)) == 2


def test_check_month_rejects_implausible_rates(btc):
    corrupted = btc.copy()
    corrupted.loc[3, "funding_rate"] = 12.0

    with pytest.raises(FundingDataError, match="implausible"):
        check_month(corrupted, BTC, JUNE)


def test_the_sanity_bound_is_far_wider_than_real_data(btc, bonk):
    """The bound exists to catch corruption, not to police the venue's own limits.

    It cannot be the published cap: `/fapi/v1/fundingInfo` is geo-blocked (B-004). So it
    must sit well clear of genuine values, including a thin symbol's much wider swings.
    """
    widest = max(btc["funding_rate"].abs().max(), bonk["funding_rate"].abs().max())

    assert widest < RATE_SANITY_BOUND / 100


# --- coverage: listing months and truncation ----------------------------------


def listing_month() -> pd.DataFrame:
    """A month starting mid-way and re-cadencing, like ``0GUSDT`` 2025-09 (4h then 1h).

    Real shape, reduced: coverage begins on the 17th and the interval changes partway. The
    old count check skipped itself entirely on months like this, so a month missing half
    its settlements would have passed.
    """
    start = int(dt.datetime(2025, 9, 17, 16, tzinfo=dt.UTC).timestamp() * 1000)
    end = int(dt.datetime(2025, 10, 1, tzinfo=dt.UTC).timestamp() * 1000)
    times, intervals, t = [start], [4], start
    while t < end - MS_PER_HOUR:
        interval = 4 if len(times) < 30 else 1
        t += interval * MS_PER_HOUR
        times.append(t)
        intervals.append(interval)
    return pd.DataFrame(
        {
            "funding_time": pd.array(times, dtype="int64"),
            "symbol": pd.array(["0GUSDT"] * len(times), dtype="string"),
            "funding_rate": [0.00005] * len(times),
            "funding_interval_hours": pd.array(intervals, dtype="int64"),
            "date": pd.array(
                [f"2025-09-{dt.datetime.fromtimestamp(x / 1000, dt.UTC).day:02d}" for x in times],
                dtype="string",
            ),
        }
    )


def test_a_listing_month_is_accepted_but_reported():
    """A symbol listed mid-month legitimately has no earlier settlements."""
    report = check_month(listing_month(), "0GUSDT", dt.date(2025, 9, 1))

    assert report.partial_start is True
    assert report.intervals == (1, 4)
    assert len(report.interval_changes) == 1


def test_a_mixed_interval_month_still_has_its_coverage_checked(tmp_path):
    """The regression this replaced: multiple intervals used to skip the check entirely."""
    truncated = listing_month().iloc[:-40].reset_index(drop=True)

    with pytest.raises(FundingDataError, match="short of the month end"):
        check_month(truncated, "0GUSDT", dt.date(2025, 9, 1))


def test_a_full_month_is_not_flagged_as_partial(btc):
    assert check_month(btc, BTC, JUNE).partial_start is False


def test_an_interval_column_disagreeing_with_the_actual_cadence_is_caught():
    """What the exact-count check still earns its place for.

    Continuity and endpoint coverage between them imply the count -- *if* the interval
    column is truthful. Label every row 8h while settling every 4h and neither fires: each
    step is shorter than its stated interval, so it is not a gap, and both endpoints are
    covered. Only the count notices there are twice as many settlements as 8h allows.
    """
    start = int(dt.datetime(2026, 6, 1, tzinfo=dt.UTC).timestamp() * 1000)
    n = 30 * 6  # a full June at a real 4h cadence
    times = [start + i * 4 * MS_PER_HOUR for i in range(n)]
    frame = pd.DataFrame(
        {
            "funding_time": pd.array(times, dtype="int64"),
            "symbol": pd.array([BTC] * n, dtype="string"),
            "funding_rate": [0.0001] * n,
            "funding_interval_hours": pd.array([8] * n, dtype="int64"),  # the lie
            "date": pd.array(["2026-06-01"] * n, dtype="string"),
        }
    )

    assert settlement_gaps(frame) == []
    with pytest.raises(FundingDataError, match="180 settlements, expected 90"):
        check_month(frame, BTC, JUNE)


def test_truncated_coverage_is_rejected_even_at_a_single_interval(btc):
    with pytest.raises(FundingDataError, match="short of the month end"):
        check_month(btc.iloc[:-5].reset_index(drop=True), BTC, JUNE)


# --- storage (criterion 6) ----------------------------------------------------


def test_store_round_trips(tmp_path, btc):
    store(btc, root=tmp_path)

    back = read_parquet(tmp_path / "funding")[btc.columns].sort_values(
        "funding_time", ignore_index=True
    )

    pd.testing.assert_frame_equal(back, btc, check_exact=True, check_dtype=True)


def test_refetching_a_month_is_idempotent(tmp_path, btc):
    store(btc, root=tmp_path)
    store(btc, root=tmp_path)

    assert len(read_parquet(tmp_path / "funding")) == len(btc)


def test_backfill_stores_what_it_fetched(tmp_path, btc_raw):
    csv = btc_raw.to_csv(index=False).encode()

    with archive_client(csv) as client:
        skipped, reports = backfill(BTC, JUNE, dt.date(2026, 6, 30), root=tmp_path, client=client)

    stored = read_parquet(tmp_path / "funding")

    assert skipped == []
    assert [r.settlements for r in reports] == [90]
    assert reports[0].intervals == (8,)
    assert not reports[0].partial_start
    assert len(stored) == 90
    assert set(stored["funding_interval_hours"]) == {8}


def test_backfill_refuses_a_month_whose_settlements_spill_into_the_next(tmp_path, btc_raw):
    """Same silent data-loss path as M1-T1: the next month's write deletes them."""
    spilled = btc_raw.copy()
    last = spilled.index[-1]
    spilled.loc[last, "calc_time"] = str(int(spilled.loc[last, "calc_time"]) + 40 * 86_400_000)

    with (
        archive_client(spilled.to_csv(index=False).encode()) as client,
        pytest.raises(FundingDataError, match="outside the month"),
    ):
        backfill(BTC, JUNE, dt.date(2026, 6, 30), root=tmp_path, client=client)

    assert not (tmp_path / "funding").exists()


def test_backfill_refuses_a_month_with_a_gap(tmp_path):
    csv = (FIXTURES / f"{BONK}-fundingRate-2026-06.csv").read_bytes()

    with archive_client(csv) as client, pytest.raises(FundingDataError, match="gap"):
        backfill(BONK, JUNE, dt.date(2026, 6, 30), root=tmp_path, client=client)

    assert not (tmp_path / "funding").exists()


def test_checksum_mismatch_is_fatal(btc_raw):
    csv = btc_raw.to_csv(index=False).encode()

    with archive_client(csv, checksum="0" * 64) as client, pytest.raises(ChecksumMismatch):
        fetch_month(BTC, "2026-06", client=client)


# --- the incomplete current month (criterion 7) -------------------------------


def test_an_absent_current_month_raises_by_default(tmp_path):
    """Monthly-only publishing means the current month 404s rather than arriving partial."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(DownloadError, match="404"),
    ):
        backfill(BTC, dt.date(2026, 8, 1), dt.date(2026, 8, 31), root=tmp_path, client=client)


def test_a_short_month_is_never_stored_as_complete(tmp_path, btc_raw):
    """Belt and braces: were a partial month ever served, it must not pass silently."""
    partial = btc_raw.iloc[:40]  # truncated end: the month has closed, so this is a defect

    with (
        archive_client(partial.to_csv(index=False).encode()) as client,
        pytest.raises(FundingDataError, match="short of the month end"),
    ):
        backfill(BTC, JUNE, dt.date(2026, 6, 30), root=tmp_path, client=client)

    assert not (tmp_path / "funding").exists()


# --- against the live archive -------------------------------------------------


@pytest.mark.network
def test_live_month_matches_the_committed_fixture(btc):
    """Detects upstream schema or content drift in the fixture's own month."""
    live = fetch_month(BTC, "2026-06")

    pd.testing.assert_frame_equal(live, btc, check_exact=True, check_dtype=True)
