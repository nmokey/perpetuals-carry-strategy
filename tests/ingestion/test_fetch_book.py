"""M1-T3 acceptance tests.

**Every fixture here is synthetic, and that is a licence requirement rather than a
convenience.** Tardis's terms permit downloading and analysing the data but forbid
redistributing raw rows (Clause 9.2(2)); committing a real book fixture would publish
vendor data through the repository and push it into CI. The Binance-archive fixtures used
by the other ingestion tests carry no such restriction -- this module's do not exist.

The one test that touches real vendor data is marked ``network``, so it is deselected by
default and never runs in CI (convention C10).
"""

import datetime as dt
import gzip
import io
import shutil

import httpx
import pandas as pd
import pytest

from perpcarry.ingestion import tardis_archive as tardis
from perpcarry.ingestion.download import DownloadError
from perpcarry.ingestion.fetch_book import (
    DEFAULT_CHUNKSIZE,
    SCHEMA,
    SNAPSHOT_SCHEMA,
    BookDataError,
    backfill,
    cache_path,
    fetch_day,
    ingest,
    iter_chunks,
    normalise,
    normalise_snapshot,
    partition_path,
    snapshot_depth,
)
from perpcarry.storage import read_parquet

SYMBOL = "0GUSDT"
DAY = dt.date(2026, 6, 1)
DAY_START_US = int(dt.datetime(2026, 6, 1, tzinfo=dt.UTC).timestamp() * 1_000_000)

COLUMNS = [
    "exchange",
    "symbol",
    "timestamp",
    "local_timestamp",
    "is_snapshot",
    "side",
    "price",
    "amount",
]


def day_start_us(day: dt.date) -> int:
    return int(dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC).timestamp() * 1_000_000)


def row(
    *,
    offset_us: int,
    is_snapshot: bool = False,
    side: str = "bid",
    price: str = "0.1424",
    amount: str = "1000",
    latency_us: int = 250,
    symbol: str = SYMBOL,
    day: dt.date = DAY,
) -> dict:
    """One synthetic vendor row. Microsecond timestamps, as the vendor emits."""
    timestamp = day_start_us(day) + offset_us
    return {
        "exchange": "binance-futures",
        "symbol": symbol,
        "timestamp": str(timestamp),
        "local_timestamp": str(timestamp + latency_us),
        "is_snapshot": "true" if is_snapshot else "false",
        "side": side,
        "price": price,
        "amount": amount,
    }


def book_day(n_diffs: int = 6, *, snapshot_rows: int = 4, **kwargs) -> list[dict]:
    """A well-formed day: an opening snapshot block, then diffs."""
    rows = [
        row(offset_us=1_000_000 + i, is_snapshot=True, price=f"0.14{20 + i:02d}", **kwargs)
        for i in range(snapshot_rows)
    ]
    rows += [
        row(offset_us=2_000_000 + i * 1000, price=f"0.14{30 + i:02d}", **kwargs)
        for i in range(n_diffs)
    ]
    return rows


def snapshot_columns(depth: int = 25) -> list[str]:
    """The vendor's wide layout: asks[0], bids[0], asks[1], bids[1], ... interleaved."""
    cols = ["exchange", "symbol", "timestamp", "local_timestamp"]
    for level in range(depth):
        for prefix in ("asks", "bids"):
            cols += [f"{prefix}[{level}].price", f"{prefix}[{level}].amount"]
    return cols


def snapshot_row(
    *,
    offset_us: int,
    depth: int = 25,
    present: int | None = None,
    day: dt.date = DAY,
    latency_us: int = 250,
    symbol: str = SYMBOL,
) -> dict:
    """One wide book image. ``present`` < ``depth`` leaves trailing levels empty."""
    timestamp = day_start_us(day) + offset_us
    filled = depth if present is None else present
    values = {
        "exchange": "binance-futures",
        "symbol": symbol,
        "timestamp": str(timestamp),
        "local_timestamp": str(timestamp + latency_us),
    }
    for level in range(depth):
        ask, bid = ("", ""), ("", "")
        if level < filled:
            ask = (f"{0.4192 + level * 0.0001:.4f}", str(100 + level))
            bid = (f"{0.4191 - level * 0.0001:.4f}", str(200 + level))
        values[f"asks[{level}].price"], values[f"asks[{level}].amount"] = ask
        values[f"bids[{level}].price"], values[f"bids[{level}].amount"] = bid
    return values


def snapshot_day(n: int = 3, *, depth: int = 25, **kwargs) -> list[dict]:
    return [snapshot_row(offset_us=1_000_000 + i * 1000, depth=depth, **kwargs) for i in range(n)]


def gzipped_snapshot(rows: list[dict], depth: int = 25) -> bytes:
    frame = pd.DataFrame(rows, columns=snapshot_columns(depth))
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as handle:
        handle.write(frame.to_csv(index=False).encode())
    return buf.getvalue()


def gzipped(rows: list[dict]) -> bytes:
    frame = pd.DataFrame(rows, columns=COLUMNS)
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as handle:
        handle.write(frame.to_csv(index=False).encode())
    return buf.getvalue()


def write_gz(tmp_path, rows: list[dict], name: str = "book.csv.gz"):
    path = tmp_path / name
    path.write_bytes(gzipped(rows))
    return path


def raw_frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=COLUMNS).astype(str)


def vendor_client(payloads: dict[str, bytes] | bytes) -> httpx.Client:
    """Serve gzipped CSVs, keyed by dataset name when a dict is given."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".CHECKSUM"):
            return httpx.Response(404)  # the vendor publishes none
        if isinstance(payloads, bytes):
            return httpx.Response(200, content=payloads)
        for dataset, payload in payloads.items():
            if f"/{dataset}/" in request.url.path:
                return httpx.Response(200, content=payload)
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


# --- Test 1: schema and the microsecond normalisation --------------------------------


def test_normalise_matches_the_section_3_2_schema():
    frame = normalise(raw_frame(book_day()), SYMBOL, DAY)

    assert list(frame.columns) == SCHEMA.names
    assert str(frame["is_snapshot"].dtype) == "bool"
    assert str(frame["price"].dtype) == "float64"
    assert str(frame["quantity"].dtype) == "float64"


def test_timestamps_are_normalised_from_microseconds_to_milliseconds():
    rows = [row(offset_us=1_245_000, is_snapshot=True)]

    frame = normalise(raw_frame(rows), SYMBOL, DAY)

    expected_ms = (DAY_START_US + 1_245_000) // 1000
    assert frame["timestamp"].iloc[0] == expected_ms
    # Sanity: a millisecond epoch for 2026 is 13 digits, a microsecond one 16.
    assert len(str(int(frame["timestamp"].iloc[0]))) == 13


def test_latency_is_computed_before_the_millisecond_conversion():
    """D-013: sub-millisecond capture latency must survive.

    Converting both columns to milliseconds first and subtracting after would quantise a
    250 microsecond gap to zero -- silently discarding the only latency signal the feed
    carries, and doing it in the direction that makes the data look better than it is.
    """
    rows = [row(offset_us=1_000_000, is_snapshot=True, latency_us=250)]

    frame = normalise(raw_frame(rows), SYMBOL, DAY)

    assert frame["latency_us"].iloc[0] == 250
    assert frame["timestamp"].iloc[0] == frame["local_timestamp"].iloc[0]  # same ms


def test_amount_maps_to_quantity():
    frame = normalise(raw_frame([row(offset_us=1, is_snapshot=True, amount="1234.5")]), SYMBOL, DAY)
    assert frame["quantity"].iloc[0] == 1234.5


# --- Test 2: the file must open with a snapshot block --------------------------------


def test_a_file_opening_with_a_snapshot_is_accepted(tmp_path):
    report = ingest(write_gz(tmp_path, book_day()), SYMBOL, DAY, root=tmp_path)

    assert report.rows == 10
    assert report.snapshot_rows == 4


def test_a_file_not_opening_with_a_snapshot_is_rejected(tmp_path):
    rows = [row(offset_us=1_000_000)] + book_day()

    with pytest.raises(BookDataError, match="does not open with an is_snapshot block"):
        ingest(write_gz(tmp_path, rows), SYMBOL, DAY, root=tmp_path)


def test_a_rejected_file_leaves_no_partition_behind(tmp_path):
    """A half-written partition reads as a thin day, which is worse than none."""
    rows = [row(offset_us=1_000_000)] + book_day()

    with pytest.raises(BookDataError):
        ingest(write_gz(tmp_path, rows), SYMBOL, DAY, root=tmp_path)

    assert not partition_path(tardis.INCREMENTAL_BOOK_L2, SYMBOL, DAY, tmp_path).exists()


def test_a_mid_file_snapshot_is_counted_as_a_resync(tmp_path):
    """Legitimate, but M2's replayer must reset state there rather than apply a diff."""
    rows = book_day(n_diffs=3) + [row(offset_us=9_000_000, is_snapshot=True)]

    report = ingest(write_gz(tmp_path, rows), SYMBOL, DAY, root=tmp_path)

    assert report.resync_events == 1
    assert report.resync_rows == 1
    assert report.snapshot_rows == 5


def test_the_opening_block_is_not_counted_as_a_resync(tmp_path):
    report = ingest(write_gz(tmp_path, book_day()), SYMBOL, DAY, root=tmp_path)
    assert report.resync_events == 0
    assert report.resync_rows == 0


def test_a_resync_split_across_chunks_is_still_counted(tmp_path):
    rows = book_day(n_diffs=3) + [row(offset_us=9_000_000, is_snapshot=True)]

    report = ingest(write_gz(tmp_path, rows), SYMBOL, DAY, root=tmp_path, chunksize=2)

    assert report.chunks > 1
    assert report.resync_events == 1
    assert report.resync_rows == 1


def test_the_is_snapshot_strings_are_parsed_not_coerced(tmp_path):
    """``bool("false")`` is ``True``; ``.astype(bool)`` would mark every row a snapshot."""
    report = ingest(write_gz(tmp_path, book_day(n_diffs=6)), SYMBOL, DAY, root=tmp_path)

    assert report.snapshot_rows == 4  # not 10


def test_an_unparseable_is_snapshot_value_is_rejected():
    rows = book_day()
    rows[0]["is_snapshot"] = "yes"

    with pytest.raises(BookDataError, match="unparseable is_snapshot"):
        normalise(raw_frame(rows), SYMBOL, DAY)


def test_a_multi_row_resync_block_is_one_event_not_many(tmp_path):
    """Rows and events are different questions, and only events tell M2 anything.

    A real day resyncs with a full ~1,400-row book image each time: 0GUSDT 2026-06-01 has
    13 events covering 18,396 rows. Reporting the rows as the resync count reads as
    thousands of resets a day.
    """
    rows = book_day(n_diffs=3) + [row(offset_us=9_000_000 + i, is_snapshot=True) for i in range(5)]

    report = ingest(write_gz(tmp_path, rows), SYMBOL, DAY, root=tmp_path)

    assert report.resync_events == 1
    assert report.resync_rows == 5


def test_two_separate_resyncs_are_two_events(tmp_path):
    rows = (
        book_day(n_diffs=2)
        + [row(offset_us=9_000_000 + i, is_snapshot=True) for i in range(3)]
        + [row(offset_us=10_000_000)]
        + [row(offset_us=11_000_000 + i, is_snapshot=True) for i in range(3)]
    )

    report = ingest(write_gz(tmp_path, rows), SYMBOL, DAY, root=tmp_path)

    assert report.resync_events == 2
    assert report.resync_rows == 6


def test_a_resync_block_split_exactly_on_a_chunk_boundary_is_one_event(tmp_path):
    """The event count carries across chunks, so a block split in two must not double."""
    rows = book_day(n_diffs=2) + [row(offset_us=9_000_000 + i, is_snapshot=True) for i in range(4)]

    report = ingest(write_gz(tmp_path, rows), SYMBOL, DAY, root=tmp_path, chunksize=8)

    assert report.chunks == 2
    assert report.resync_events == 1
    assert report.resync_rows == 4


# --- Test 3: amount = 0 is a removal, not noise --------------------------------------


def test_zero_amount_rows_are_preserved_as_removals(tmp_path):
    """Filtering quantity > 0 turns every deletion into a phantom level.

    The book would then drift further from truth with each removal and never raise --
    exactly the failure mode that makes calibrated impact numbers quietly wrong.
    """
    rows = book_day(n_diffs=2) + [
        row(offset_us=3_000_000, amount="0"),
        row(offset_us=3_100_000, amount="0", side="ask"),
    ]

    report = ingest(write_gz(tmp_path, rows), SYMBOL, DAY, root=tmp_path)
    stored = read_parquet(partition_path(tardis.INCREMENTAL_BOOK_L2, SYMBOL, DAY, tmp_path))

    assert report.removals == 2
    assert (stored["quantity"] == 0).sum() == 2
    assert report.rows == len(rows)


def test_removals_survive_the_round_trip_on_both_sides(tmp_path):
    rows = book_day(n_diffs=1) + [
        row(offset_us=3_000_000, amount="0", side="bid", price="0.1400"),
        row(offset_us=3_100_000, amount="0", side="ask", price="0.1500"),
    ]
    ingest(write_gz(tmp_path, rows), SYMBOL, DAY, root=tmp_path)

    stored = read_parquet(partition_path(tardis.INCREMENTAL_BOOK_L2, SYMBOL, DAY, tmp_path))
    removed = stored[stored["quantity"] == 0]

    assert set(removed["side"]) == {"bid", "ask"}


# --- Test 4: the free-tier limitation is named, not surfaced as a bare 401 -----------


@pytest.mark.parametrize("day", [dt.date(2026, 6, 2), dt.date(2026, 6, 15), dt.date(2026, 6, 30)])
def test_a_non_first_of_month_date_is_refused_before_any_request(day):
    with pytest.raises(tardis.FreeTierError, match="first day of each month"):
        tardis.dataset_url(tardis.INCREMENTAL_BOOK_L2, SYMBOL, day)


def test_the_refusal_names_the_usable_date():
    with pytest.raises(tardis.FreeTierError, match="2026-06-01"):
        tardis.dataset_url(tardis.INCREMENTAL_BOOK_L2, SYMBOL, dt.date(2026, 6, 17))


def test_the_refusal_says_it_is_not_an_auth_problem():
    """A bare 401 sends the reader hunting for an API key this project does not use."""
    with pytest.raises(tardis.FreeTierError, match="not an authentication failure"):
        tardis.dataset_url(tardis.INCREMENTAL_BOOK_L2, SYMBOL, dt.date(2026, 6, 17))


def test_a_first_of_month_date_is_allowed():
    url = tardis.dataset_url(tardis.INCREMENTAL_BOOK_L2, SYMBOL, DAY)
    assert url.endswith("/binance-futures/incremental_book_L2/2026/06/01/0GUSDT.csv.gz")


def test_free_tier_days_yields_only_first_of_month():
    days = list(tardis.free_tier_days(dt.date(2024, 9, 1), dt.date(2026, 8, 1)))

    assert len(days) == 24
    assert all(d.day == 1 for d in days)
    assert days[0] == dt.date(2024, 9, 1) and days[-1] == dt.date(2026, 8, 1)


def test_free_tier_days_does_not_emit_a_day_before_the_start():
    days = list(tardis.free_tier_days(dt.date(2024, 9, 15), dt.date(2024, 12, 1)))

    assert days[0] == dt.date(2024, 10, 1)
    assert all(d >= dt.date(2024, 9, 15) for d in days)


def test_an_unknown_dataset_is_rejected():
    with pytest.raises(ValueError, match="unknown dataset"):
        tardis.dataset_url("bookDepth", SYMBOL, DAY)


# --- Test 5: ingest is streaming ------------------------------------------------------


def test_iter_chunks_never_yields_more_than_the_chunk_size(tmp_path):
    path = write_gz(tmp_path, book_day(n_diffs=46))  # 50 rows

    lengths = [len(c) for c in iter_chunks(path, chunksize=10)]

    assert max(lengths) <= 10
    assert sum(lengths) == 50


def test_ingest_processes_a_large_day_in_bounded_chunks(tmp_path):
    path = write_gz(tmp_path, book_day(n_diffs=996))  # 1000 rows

    report = ingest(path, SYMBOL, DAY, root=tmp_path, chunksize=100)

    assert report.rows == 1000
    assert report.chunks == 10  # a whole-file read would report 1


def test_a_chunked_ingest_stores_every_row(tmp_path):
    path = write_gz(tmp_path, book_day(n_diffs=96))
    ingest(path, SYMBOL, DAY, root=tmp_path, chunksize=7)

    stored = read_parquet(partition_path(tardis.INCREMENTAL_BOOK_L2, SYMBOL, DAY, tmp_path))
    assert len(stored) == 100


def test_the_default_chunk_size_is_bounded():
    assert 0 < DEFAULT_CHUNKSIZE <= 1_000_000


def test_a_truncated_archive_raises_rather_than_looking_like_a_thin_day(tmp_path):
    """The vendor publishes no checksums, so inflation is the only integrity signal."""
    path = tmp_path / "truncated.csv.gz"
    path.write_bytes(gzipped(book_day(n_diffs=200))[:200])

    with pytest.raises(EOFError):
        list(iter_chunks(path, chunksize=10))


# --- Test 6: both datasets are fetched -----------------------------------------------


def test_fetch_day_pulls_both_datasets(tmp_path):
    payloads = {
        tardis.INCREMENTAL_BOOK_L2: gzipped(book_day(n_diffs=6)),
        tardis.BOOK_SNAPSHOT_25: gzipped_snapshot(snapshot_day(2)),
    }

    with vendor_client(payloads) as client:
        reports = fetch_day(SYMBOL, DAY, root=tmp_path, client=client)

    assert {r.dataset for r in reports} == set(tardis.DATASETS)
    assert partition_path(tardis.BOOK_SNAPSHOT_25, SYMBOL, DAY, tmp_path).exists()


def test_the_two_datasets_land_in_separate_directories(tmp_path):
    payloads = {
        tardis.INCREMENTAL_BOOK_L2: gzipped(book_day()),
        tardis.BOOK_SNAPSHOT_25: gzipped_snapshot(snapshot_day(2)),
    }

    with vendor_client(payloads) as client:
        fetch_day(SYMBOL, DAY, root=tmp_path, client=client)

    book = partition_path(tardis.INCREMENTAL_BOOK_L2, SYMBOL, DAY, tmp_path)
    snapshot = partition_path(tardis.BOOK_SNAPSHOT_25, SYMBOL, DAY, tmp_path)
    assert book != snapshot
    assert book.exists() and snapshot.exists()


def test_a_401_from_the_server_is_translated_not_passed_through(tmp_path):
    """Belt and braces: the date guard should prevent this, but the server may still 401."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(tardis.FreeTierError, match="tier limitation"),
    ):
        fetch_day(SYMBOL, DAY, root=tmp_path, client=client)


def test_backfill_walks_only_free_tier_days(tmp_path):
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        # Serve rows stamped for the day actually requested -- serving one day's rows for
        # every date would (correctly) trip the stray-day guard, and the resulting failure
        # would look like a backfill bug rather than a fixture bug.
        year, month, dom = (int(p) for p in request.url.path.split("/")[-4:-1])
        return httpx.Response(200, content=gzipped(book_day(day=dt.date(year, month, dom))))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        reports, skipped = backfill(
            SYMBOL,
            dt.date(2026, 6, 1),
            dt.date(2026, 8, 1),
            datasets=(tardis.INCREMENTAL_BOOK_L2,),
            root=tmp_path,
            client=client,
        )

    assert len(reports) == 3
    assert skipped == []
    assert all(p.split("/")[-2] == "01" for p in requested)


def test_backfill_refuses_a_missing_day_unless_allowed(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(DownloadError),
    ):
        backfill(
            SYMBOL,
            DAY,
            DAY,
            datasets=(tardis.INCREMENTAL_BOOK_L2,),
            root=tmp_path,
            client=client,
        )


def test_backfill_reports_skipped_days_when_allowed(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        reports, skipped = backfill(
            SYMBOL,
            dt.date(2026, 6, 1),
            dt.date(2026, 7, 1),
            datasets=(tardis.INCREMENTAL_BOOK_L2,),
            root=tmp_path,
            client=client,
            allow_missing=True,
        )

    assert reports == []
    assert skipped == [dt.date(2026, 6, 1), dt.date(2026, 7, 1)]


# --- book_snapshot_25: a different shape entirely -------------------------------------


def snapshot_raw(rows: list[dict], depth: int = 25) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=snapshot_columns(depth)).astype(str)


def test_the_wide_snapshot_is_melted_to_one_row_per_level():
    """104 wide columns in, long rows out -- see normalise_snapshot's docstring."""
    frame = normalise_snapshot(snapshot_raw(snapshot_day(2)), SYMBOL, DAY)

    assert list(frame.columns) == SNAPSHOT_SCHEMA.names
    assert len(frame) == 2 * 25 * 2  # 2 images x 25 levels x 2 sides
    assert set(frame["side"]) == {"bid", "ask"}
    assert sorted(frame["level"].unique()) == list(range(25))


def test_snapshot_levels_keep_their_prices_and_quantities():
    frame = normalise_snapshot(snapshot_raw(snapshot_day(1)), SYMBOL, DAY)

    top_ask = frame[(frame["side"] == "ask") & (frame["level"] == 0)].iloc[0]
    top_bid = frame[(frame["side"] == "bid") & (frame["level"] == 0)].iloc[0]

    assert top_ask["price"] == 0.4192
    assert top_ask["quantity"] == 100
    assert top_bid["price"] == 0.4191
    assert top_bid["quantity"] == 200


def test_a_book_thinner_than_25_levels_drops_the_empty_levels():
    """A level that does not exist is not a level with an unknown price.

    This is the *opposite* of the incremental feed, where amount = 0 is meaningful and
    must be preserved. Conflating the two conventions would either invent phantom levels
    here or destroy removals there.
    """
    frame = normalise_snapshot(snapshot_raw(snapshot_day(1, present=3)), SYMBOL, DAY)

    assert len(frame) == 3 * 2
    assert frame["price"].notna().all()
    assert sorted(frame["level"].unique()) == [0, 1, 2]


def test_snapshot_depth_is_read_from_the_columns_not_assumed():
    assert snapshot_depth(snapshot_columns(25)) == list(range(25))
    assert snapshot_depth(snapshot_columns(5)) == [0, 1, 2, 3, 4]


def test_a_frame_with_no_depth_columns_is_refused():
    frame = pd.DataFrame(
        [{"exchange": "x", "symbol": SYMBOL, "timestamp": "1", "local_timestamp": "2"}]
    )
    with pytest.raises(BookDataError, match="does not look like"):
        normalise_snapshot(frame, SYMBOL, DAY)


def test_the_snapshot_normaliser_also_converts_microseconds():
    frame = normalise_snapshot(snapshot_raw(snapshot_day(1)), SYMBOL, DAY)

    assert len(str(int(frame["timestamp"].iloc[0]))) == 13
    assert frame["latency_us"].iloc[0] == 250


def test_snapshot_ingest_shrinks_the_chunk_size(tmp_path):
    """Melting multiplies rows by up to 50, so the read chunk must shrink to match.

    Without this the bounded-memory property is lost precisely on the largest files.
    """
    path = tmp_path / "snap.csv.gz"
    path.write_bytes(gzipped_snapshot(snapshot_day(4)))

    report = ingest(
        path, SYMBOL, DAY, dataset=tardis.BOOK_SNAPSHOT_25, root=tmp_path, chunksize=100
    )

    assert report.chunks == 2  # 100 // 50 = 2 rows per chunk, 4 images
    assert report.rows == 4 * 25 * 2


def test_snapshot_ingest_lands_in_its_own_dataset_directory(tmp_path):
    path = tmp_path / "snap.csv.gz"
    path.write_bytes(gzipped_snapshot(snapshot_day(2)))

    ingest(path, SYMBOL, DAY, dataset=tardis.BOOK_SNAPSHOT_25, root=tmp_path)

    stored = read_parquet(partition_path(tardis.BOOK_SNAPSHOT_25, SYMBOL, DAY, tmp_path))
    assert set(stored.columns) >= set(SNAPSHOT_SCHEMA.names)
    assert len(stored) == 100


def test_an_unknown_dataset_cannot_be_ingested(tmp_path):
    with pytest.raises(ValueError, match="unknown dataset"):
        ingest(write_gz(tmp_path, book_day()), SYMBOL, DAY, dataset="bookDepth", root=tmp_path)


# --- Cache keying ---------------------------------------------------------------------


def test_the_cache_key_distinguishes_days():
    """Every vendor URL for a symbol ends in the same basename.

    The date is in the path (``.../2026/06/01/0GUSDT.csv.gz``), so a cache keyed on the
    filename -- which is ``cached_fetch``'s default -- serves the first day downloaded for
    all 24 months of a backfill. Silent, and it survives every schema check.
    """
    june = cache_path(tardis.INCREMENTAL_BOOK_L2, SYMBOL, dt.date(2026, 6, 1))
    july = cache_path(tardis.INCREMENTAL_BOOK_L2, SYMBOL, dt.date(2026, 7, 1))

    assert june != july


def test_the_cache_key_distinguishes_datasets():
    book = cache_path(tardis.INCREMENTAL_BOOK_L2, SYMBOL, DAY)
    snapshot = cache_path(tardis.BOOK_SNAPSHOT_25, SYMBOL, DAY)

    assert book != snapshot


def test_the_cache_key_distinguishes_symbols():
    assert cache_path(tardis.INCREMENTAL_BOOK_L2, "BTCUSDT", DAY) != cache_path(
        tardis.INCREMENTAL_BOOK_L2, "ETHUSDT", DAY
    )


def test_a_backfill_downloads_each_day_rather_than_reusing_a_cached_one(tmp_path):
    """The end-to-end version of the above: distinct bytes per day must survive."""
    served: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        served.append(request.url.path)
        year, month, dom = (int(p) for p in request.url.path.split("/")[-4:-1])
        return httpx.Response(200, content=gzipped(book_day(day=dt.date(year, month, dom))))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        backfill(
            SYMBOL,
            dt.date(2026, 6, 1),
            dt.date(2026, 8, 1),
            datasets=(tardis.INCREMENTAL_BOOK_L2,),
            root=tmp_path,
            client=client,
        )

    assert len(served) == 3  # not 1 download plus 2 cache hits
    stored = read_parquet(tmp_path / "book")
    assert set(stored["date"]) == {"2026-06-01", "2026-07-01", "2026-08-01"}


def test_the_cache_stays_inside_the_data_root(isolated_data_root):
    """Convention C9, and stricter here: vendor data must never escape the data root."""
    path = cache_path(tardis.INCREMENTAL_BOOK_L2, SYMBOL, DAY)

    assert isolated_data_root in path.parents


# --- Structural guards ----------------------------------------------------------------


def test_a_row_from_another_day_is_refused(tmp_path):
    """The whole file goes into one partition, so a stray row would be misfiled."""
    rows = book_day(n_diffs=2)
    rows.append(row(offset_us=25 * 3_600_000_000))  # next day

    with pytest.raises(BookDataError, match="other UTC day"):
        ingest(write_gz(tmp_path, rows), SYMBOL, DAY, root=tmp_path)


def test_a_file_for_the_wrong_symbol_is_refused():
    rows = book_day()
    rows[-1]["symbol"] = "BTCUSDT"

    with pytest.raises(BookDataError, match="wrong file"):
        normalise(raw_frame(rows), SYMBOL, DAY)


def test_an_unknown_side_is_refused():
    rows = book_day()
    rows[-1]["side"] = "middle"

    with pytest.raises(BookDataError, match="unknown side"):
        normalise(raw_frame(rows), SYMBOL, DAY)


def test_a_missing_vendor_column_names_what_changed():
    frame = raw_frame(book_day()).drop(columns=["local_timestamp"])

    with pytest.raises(BookDataError, match="local_timestamp"):
        normalise(frame, SYMBOL, DAY)


def test_an_empty_file_is_refused(tmp_path):
    with pytest.raises(BookDataError, match="no rows"):
        ingest(write_gz(tmp_path, []), SYMBOL, DAY, root=tmp_path)


def test_reingesting_a_day_replaces_rather_than_appends(tmp_path):
    path = write_gz(tmp_path, book_day())

    ingest(path, SYMBOL, DAY, root=tmp_path)
    ingest(path, SYMBOL, DAY, root=tmp_path)

    stored = read_parquet(partition_path(tardis.INCREMENTAL_BOOK_L2, SYMBOL, DAY, tmp_path))
    assert len(stored) == 10  # not 20


def test_a_stale_fragment_from_an_earlier_run_is_removed(tmp_path):
    """Re-ingest replaces the partition directory, not just the file it writes.

    Overwriting ``part-0.parquet`` alone would leave any *other* fragment in place --
    from an aborted run, or a version that named its files differently -- and a Hive read
    unions every file in the directory. The stale rows would be silently added to the
    day, which is indistinguishable from real data.
    """
    path = write_gz(tmp_path, book_day())
    ingest(path, SYMBOL, DAY, root=tmp_path)

    partition = partition_path(tardis.INCREMENTAL_BOOK_L2, SYMBOL, DAY, tmp_path)
    stale = partition / "part-0001.parquet"
    shutil.copy(partition / "part-0.parquet", stale)
    assert len(read_parquet(partition)) == 20  # the stale copy is being read

    ingest(path, SYMBOL, DAY, root=tmp_path)

    assert not stale.exists()
    assert len(read_parquet(partition)) == 10


def test_the_partition_layout_is_hive_symbol_then_date(tmp_path):
    ingest(write_gz(tmp_path, book_day()), SYMBOL, DAY, root=tmp_path)

    expected = tmp_path / "book" / f"symbol={SYMBOL}" / "date=2026-06-01"
    assert expected.is_dir()
    assert list(expected.glob("*.parquet"))


def test_partition_columns_are_recoverable_on_read(tmp_path):
    ingest(write_gz(tmp_path, book_day()), SYMBOL, DAY, root=tmp_path)

    stored = read_parquet(tmp_path / "book")
    assert set(stored["symbol"]) == {SYMBOL}
    assert set(stored["date"]) == {"2026-06-01"}


# --- Licence guard --------------------------------------------------------------------


def test_no_vendor_fixture_is_committed():
    """The licence forbids redistributing raw rows; this module's fixtures are synthetic.

    A future contributor reaching for a real book day as a fixture is the plausible
    mistake, and it would be a licence breach rather than a test-quality problem.
    """
    from pathlib import Path

    fixtures = Path(__file__).parent / "fixtures"
    vendor = [
        p
        for p in fixtures.iterdir()
        if "book" in p.name.lower() or "tardis" in p.name.lower() or "L2" in p.name
    ]
    assert vendor == [], f"vendor book fixtures must not be committed: {vendor}"


# --- Real vendor data (network, never in CI) ------------------------------------------


@pytest.mark.network
def test_a_real_vendor_day_ingests(tmp_path):
    """0GUSDT is ~10 MB/day against BTCUSDT's 449 MB, so this stays cheap."""
    reports = fetch_day(SYMBOL, DAY, root=tmp_path, chunksize=50_000)

    book = next(r for r in reports if r.dataset == tardis.INCREMENTAL_BOOK_L2)
    assert book.rows > 0
    assert book.snapshot_rows > 0
    assert book.removals > 0  # a real day always deletes levels
    assert len(reports) == 2


@pytest.mark.network
def test_the_free_tier_really_does_reject_the_second_of_the_month():
    """Pins the probe finding that justifies the whole free_tier_days design."""
    url = f"{tardis.BASE}/{tardis.EXCHANGE}/{tardis.INCREMENTAL_BOOK_L2}/2026/06/02/{SYMBOL}.csv.gz"

    response = httpx.get(url, follow_redirects=True, timeout=30)

    assert response.status_code == 401
