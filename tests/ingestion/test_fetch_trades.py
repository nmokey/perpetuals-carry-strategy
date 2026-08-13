"""M1-T1 acceptance tests.

The offline fixture is 200 real rows from the Binance archive rather than synthesised
data, so an upstream schema change fails here instead of silently producing a wrong
frame. Archive data only -- never vendor book data, which the licence forbids
redistributing (see specs/M1/M1-T3).
"""

import datetime as dt
import zipfile
from decimal import Decimal
from pathlib import Path

import httpx
import pandas as pd
import pytest

from perpcarry.ingestion import binance_archive as archive
from perpcarry.ingestion.download import ChecksumMismatch, DownloadError
from perpcarry.ingestion.fetch_trades import (
    SCHEMA,
    TradeDataError,
    backfill,
    duplicate_trade_ids,
    fetch_day,
    months_between,
    normalise,
    store,
    total_quantity,
    trade_id_gaps,
)
from perpcarry.storage import read_parquet

FIXTURE = Path(__file__).parent / "fixtures" / "0GUSDT-trades-2026-08-01.head.csv"
SYMBOL = "0GUSDT"


@pytest.fixture
def raw() -> pd.DataFrame:
    return pd.read_csv(FIXTURE, dtype=str)


@pytest.fixture
def frame(raw) -> pd.DataFrame:
    return normalise(raw, SYMBOL)


def zipped(csv_bytes: bytes, name: str = "t.csv") -> bytes:
    import io

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(name, csv_bytes)
    return buf.getvalue()


def dated(raw: pd.DataFrame, month: dt.date, *, id_offset: int = 0) -> pd.DataFrame:
    """Re-stamp a fixture into ``month`` so it passes the spill guard.

    ``backfill`` refuses a monthly archive containing dates outside its own month, so
    multi-month tests must produce month-appropriate timestamps rather than reusing one
    fixture's dates everywhere.
    """
    start_ms = int(dt.datetime(month.year, month.month, 1, tzinfo=dt.UTC).timestamp() * 1000)
    out = raw.copy()
    out["time"] = [str(start_ms + i * 1000) for i in range(len(out))]
    out["id"] = (out["id"].astype("int64") + id_offset).astype(str)
    return out


def archive_client(csv_bytes: bytes, *, checksum: str | None = None) -> httpx.Client:
    """Serve a zipped CSV, plus its .CHECKSUM when one is given."""
    payload = zipped(csv_bytes)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".CHECKSUM"):
            if checksum is None:
                return httpx.Response(404)
            return httpx.Response(200, text=f"{checksum}  x.zip\n")
        return httpx.Response(200, content=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


# --- schema (criterion 4) -----------------------------------------------------


def test_output_matches_section_3_1_schema(frame):
    assert list(frame.columns) == list(SCHEMA)
    assert {c: str(d) for c, d in frame.dtypes.items()} == SCHEMA


def test_symbol_is_injected_from_the_request_not_the_file(frame):
    assert set(frame["symbol"]) == {SYMBOL}


def test_date_is_derived_from_each_trade_not_the_requested_day(frame):
    # Fixture is a 2026-08-01 file; the partition key must come from the timestamps.
    assert set(frame["date"]) == {"2026-08-01"}


def test_schema_drift_is_rejected(raw):
    with pytest.raises(TradeDataError, match="missing columns"):
        normalise(raw.drop(columns=["is_buyer_maker"]), SYMBOL)


# --- aggressor side (criterion 2) --------------------------------------------


def test_is_buyer_maker_true_means_the_aggressor_sold():
    raw = pd.DataFrame(
        {
            "id": ["1", "2"],
            "price": ["1.0", "2.0"],
            "qty": ["3.0", "4.0"],
            "time": ["1785542400081", "1785542400082"],
            "is_buyer_maker": ["true", "false"],
        }
    )

    assert list(normalise(raw, SYMBOL)["side"]) == ["sell", "buy"]


def test_real_fixture_has_both_sides(frame):
    """Guards against a mapping that collapses everything to one side.

    Not hypothetical: the first implementation called ``.astype(bool)`` on the string
    column, and ``bool("false") is True``, so every trade came back a sell.
    """
    assert set(frame["side"]) == {"buy", "sell"}


def test_string_and_boolean_maker_columns_agree():
    """The archive is read as strings; a bool column must not take a different path."""
    as_str = pd.DataFrame(
        {
            "id": ["1", "2"],
            "price": ["1.0", "2.0"],
            "qty": ["3.0", "4.0"],
            "time": ["1785542400081", "1785542400082"],
            "is_buyer_maker": ["TRUE ", "false"],
        }
    )
    as_bool = as_str.assign(is_buyer_maker=[True, False])

    assert list(normalise(as_str, SYMBOL)["side"]) == list(normalise(as_bool, SYMBOL)["side"])


def test_unparseable_maker_value_is_rejected():
    raw = pd.DataFrame(
        {
            "id": ["1"],
            "price": ["1.0"],
            "qty": ["3.0"],
            "time": ["1785542400081"],
            "is_buyer_maker": ["yes"],
        }
    )

    with pytest.raises(TradeDataError, match="unparseable"):
        normalise(raw, SYMBOL)


# --- trade_id continuity (criterion 1) ---------------------------------------


def test_real_fixture_is_contiguous(frame):
    assert trade_id_gaps(frame) == []


def test_a_synthetic_gap_is_detected_and_located(frame):
    punched = frame.drop(index=5).reset_index(drop=True)

    gaps = trade_id_gaps(punched)

    assert len(gaps) == 1
    prev, nxt = gaps[0]
    assert nxt - prev == 2


def test_gaps_are_empty_for_degenerate_frames(frame):
    assert trade_id_gaps(frame.head(1)) == []
    assert trade_id_gaps(frame.head(0)) == []


def test_duplicates_are_reported_separately_from_gaps():
    """Different cause (overlapping re-fetch vs lost data), so a different error."""
    frame = pd.DataFrame({"trade_id": [1, 2, 2, 3]})

    assert trade_id_gaps(frame) == []
    assert duplicate_trade_ids(frame) == [2]


def test_backfill_stores_the_rows_it_fetched(tmp_path, raw):
    """The happy path. Everything else here tests refusal; this tests that it works.

    Without it, ``backfill`` could store nothing at all and the suite stayed green.
    """
    csv = raw.to_csv(index=False).encode()

    with archive_client(csv) as client:
        skipped = backfill(
            SYMBOL, dt.date(2026, 8, 1), dt.date(2026, 8, 31), root=tmp_path, client=client
        )

    assert skipped == []
    stored = read_parquet(tmp_path / "trades")
    expected = normalise(raw, SYMBOL)
    assert len(stored) == len(expected)
    assert set(stored["trade_id"]) == set(expected["trade_id"])
    assert set(stored["side"]) == {"buy", "sell"}
    assert set(stored["date"]) == {"2026-08-01"}


def test_backfill_stores_every_month_in_the_range(tmp_path, raw):
    """Two months in, two months' rows out -- a silent early exit would pass otherwise."""
    payloads = [
        dated(raw, dt.date(2026, 8, 1)),
        dated(raw, dt.date(2026, 9, 1), id_offset=len(raw)),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".CHECKSUM"):
            return httpx.Response(404)
        return httpx.Response(200, content=zipped(payloads.pop(0).to_csv(index=False).encode()))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        backfill(SYMBOL, dt.date(2026, 8, 1), dt.date(2026, 9, 30), root=tmp_path, client=client)

    stored = read_parquet(tmp_path / "trades")

    assert len(stored) == 2 * len(raw)
    assert len(set(stored["date"])) == 2


def test_backfill_refuses_a_month_whose_rows_spill_into_the_next(tmp_path, raw):
    """Silent data loss otherwise.

    Rows dated outside the month land in the *next* month's partition; writing that month
    then deletes them, because ``write_parquet`` uses ``delete_matching``. Demonstrated:
    two rows in, one row silently gone. Observed archives are clean, but the failure is
    invisible, so it must be refused rather than trusted.
    """
    spilled = raw.copy()
    spilled.loc[spilled.index[-1], "time"] = str(int(spilled["time"].iloc[-1]) + 40 * 86_400_000)
    csv = spilled.to_csv(index=False).encode()

    with archive_client(csv) as client, pytest.raises(TradeDataError, match="outside the month"):
        backfill(SYMBOL, dt.date(2026, 8, 1), dt.date(2026, 8, 31), root=tmp_path, client=client)


def test_backfill_detects_a_gap_across_a_month_boundary(tmp_path, raw):
    """A whole missing file between two intact months leaves both looking perfect.

    Per-month checks cannot see this; the design doc criterion says "contiguous within
    and across days", so the boundary must be carried between fetches.
    """
    payloads = [
        dated(raw, dt.date(2026, 7, 1)),
        # Second month starts far past where the first ended.
        dated(raw, dt.date(2026, 8, 1), id_offset=10_000),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".CHECKSUM"):
            return httpx.Response(404)
        return httpx.Response(200, content=zipped(payloads.pop(0).to_csv(index=False).encode()))

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(TradeDataError, match="across the boundary"),
    ):
        backfill(SYMBOL, dt.date(2026, 7, 1), dt.date(2026, 8, 31), root=tmp_path, client=client)


def test_backfill_does_not_flag_a_boundary_after_an_allowed_skip(tmp_path, raw):
    """A skipped month legitimately breaks the sequence -- don't call that a data gap.

    The order matters: a month must *succeed* before the skip, or the boundary state was
    never set and the reset is untested. An earlier version of this test started with the
    404 and passed even with the reset deleted.
    """
    # Jul succeeds, Aug is unlisted, Sep resumes far ahead of Jul.
    responses: list[pd.DataFrame | None] = [
        dated(raw, dt.date(2026, 7, 1)),
        None,
        dated(raw, dt.date(2026, 9, 1), id_offset=10_000),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".CHECKSUM"):
            return httpx.Response(404)
        payload = responses.pop(0)
        if payload is None:
            return httpx.Response(404)
        return httpx.Response(200, content=zipped(payload.to_csv(index=False).encode()))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        skipped = backfill(
            SYMBOL,
            dt.date(2026, 7, 1),
            dt.date(2026, 9, 30),
            root=tmp_path,
            client=client,
            allow_missing=True,
        )

    assert skipped == [dt.date(2026, 8, 1)]


def test_backfill_refuses_a_month_with_duplicate_trade_ids(tmp_path, raw):
    """Duplicates mean an overlapping re-fetch, and must not be stored."""
    doubled = pd.concat([raw, raw.iloc[[5]]], ignore_index=True)
    csv = doubled.to_csv(index=False).encode()

    with archive_client(csv) as client, pytest.raises(TradeDataError, match="duplicate trade_id"):
        backfill(SYMBOL, dt.date(2026, 8, 1), dt.date(2026, 8, 31), root=tmp_path, client=client)

    assert not (tmp_path / "trades").exists()


def test_klines_volume_verifies_the_published_checksum():
    """A corrupt klines file would otherwise read as a reconciliation failure."""
    from perpcarry.ingestion.fetch_trades import klines_volume

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".CHECKSUM"):
            return httpx.Response(200, text=f"{'0' * 64}  k.zip\n")
        return httpx.Response(200, content=zipped(b"0,1,2,3,4,5,6,7,8,9,10,11\n", "k.csv"))

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(ChecksumMismatch),
    ):
        klines_volume(SYMBOL, "2026-08-01", client=client)


def test_backfill_refuses_a_month_with_a_gap(tmp_path, raw):
    punched = raw.drop(index=5)
    csv = punched.to_csv(index=False).encode()

    with archive_client(csv) as client, pytest.raises(TradeDataError, match="trade_id gap"):
        backfill(SYMBOL, dt.date(2026, 8, 1), dt.date(2026, 8, 1), root=tmp_path, client=client)

    assert not (tmp_path / "trades").exists(), "a gapped month must not be stored"


# --- storage round trip (criteria 4, 5) --------------------------------------


def test_store_round_trips_through_parquet(tmp_path, frame):
    store(frame, root=tmp_path)

    back = read_parquet(tmp_path / "trades")[frame.columns]
    back = back.sort_values("trade_id", ignore_index=True)

    pd.testing.assert_frame_equal(back, frame, check_exact=True, check_dtype=True)


def test_refetching_a_date_is_idempotent(tmp_path, frame):
    store(frame, root=tmp_path)
    store(frame, root=tmp_path)

    assert len(read_parquet(tmp_path / "trades")) == len(frame)


def test_partition_layout_is_symbol_then_date(tmp_path, frame):
    store(frame, root=tmp_path)

    dirs = {
        str(p.relative_to(tmp_path / "trades"))
        for p in (tmp_path / "trades").rglob("*")
        if p.is_dir()
    }

    assert f"symbol={SYMBOL}" in dirs
    assert f"symbol={SYMBOL}/date=2026-08-01" in dirs


# --- fetching (criteria 6, 7) ------------------------------------------------


def test_fetch_day_verifies_the_published_checksum(raw):
    csv = raw.to_csv(index=False).encode()

    with archive_client(csv, checksum="0" * 64) as client, pytest.raises(ChecksumMismatch):
        fetch_day(SYMBOL, "2026-08-01", client=client)


def test_missing_archive_names_the_url(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(DownloadError, match=r"404.*0GUSDT-trades-2026-08-01"),
    ):
        fetch_day(SYMBOL, "2026-08-01", client=client, verify_checksum=False)


def test_backfill_skips_unlisted_months_only_when_allowed(tmp_path):
    """A 404 before a symbol's listing date is explainable -- but never silent."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(DownloadError):
            backfill(
                SYMBOL, dt.date(2024, 9, 1), dt.date(2024, 9, 30), root=tmp_path, client=client
            )

        skipped = backfill(
            SYMBOL,
            dt.date(2024, 9, 1),
            dt.date(2024, 10, 31),
            root=tmp_path,
            client=client,
            allow_missing=True,
        )

    assert skipped == [dt.date(2024, 9, 1), dt.date(2024, 10, 1)]


# --- URL construction --------------------------------------------------------


def test_klines_url_keeps_the_interval_segment():
    """The one path shape that differs; reusing the flat builder 404s silently."""
    url = archive.klines_daily_url("BTCUSDT", "2026-08-01")

    assert url.endswith("/klines/BTCUSDT/1m/BTCUSDT-1m-2026-08-01.zip")


def test_trades_url_has_no_interval_segment():
    assert archive.daily_url("trades", "BTCUSDT", dt.date(2026, 8, 1)).endswith(
        "/daily/trades/BTCUSDT/BTCUSDT-trades-2026-08-01.zip"
    )


def test_months_between_covers_year_boundaries():
    months = list(months_between(dt.date(2024, 11, 15), dt.date(2025, 2, 1)))

    assert months == [
        dt.date(2024, 11, 1),
        dt.date(2024, 12, 1),
        dt.date(2025, 1, 1),
        dt.date(2025, 2, 1),
    ]


# --- quantity ----------------------------------------------------------------


def test_total_quantity_is_exact(frame):
    assert total_quantity(frame) == sum(Decimal(str(q)) for q in frame["quantity"])
    assert isinstance(total_quantity(frame), Decimal)


# --- against the live archive (criterion 3) ----------------------------------


@pytest.mark.network
def test_day_reconciles_exactly_with_klines_volume():
    """The 'consistent with venue-reported volume' criterion, as an equality."""
    from perpcarry.ingestion.fetch_trades import klines_volume

    frame = fetch_day(SYMBOL, "2026-08-01")

    assert trade_id_gaps(frame) == []
    assert total_quantity(frame) == klines_volume(SYMBOL, "2026-08-01")
