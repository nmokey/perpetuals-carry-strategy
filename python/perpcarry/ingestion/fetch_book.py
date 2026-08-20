"""Historical L2 order book downloader (design-doc M1-T3).

Pulls the Tardis.dev free tier's ``incremental_book_L2`` (snapshot + diffs) and the
matching ``book_snapshot_25`` reference, normalises both onto the §3.2 schema, and stores
them as partitioned Parquet. This is what makes the project's central claim possible --
that execution costs are *calibrated* from real book data rather than assumed -- so the
fidelity obtained here bounds what M9 may honestly assert.

Three things constrain the implementation, and none of them are optional.

**Nothing may be loaded whole.** A BTCUSDT book day is ~449 MB compressed and several
gigabytes inflated. The CSV is read in chunks and written to Parquet row-group by row
group; :func:`perpcarry.storage.write_parquet` is deliberately *not* used here because it
materialises an entire frame.

**``amount = 0`` means the level was removed, not that the row is noise.** Filtering
``quantity > 0`` while cleaning would turn every deletion into a permanently phantom
level, and the replayed book would drift without ever raising. The removals are counted
into the ingest report so the property is visible rather than merely asserted once.

**The licence forbids redistributing raw rows.** Vendor data may be downloaded and
analysed locally, but must never be committed as a test fixture, published, or allowed to
reach CI (M1-T3's Licence section, stricter than convention C9). Every fixture in the test
suite for this module is therefore synthetic.

Integrity: the vendor publishes no checksums (verified 404), so successful gzip inflation
is the signal -- a truncated ``.gz`` raises ``EOFError`` before the end-of-stream marker,
so a partial download cannot pass silently.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import logging
import re
import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from perpcarry.ingestion import tardis_archive as tardis
from perpcarry.ingestion.download import DownloadError, cache_dir, cached_fetch
from perpcarry.storage import data_root

log = logging.getLogger(__name__)

#: Rows per read chunk. Bounded memory matters more than throughput here.
DEFAULT_CHUNKSIZE = 500_000

#: Dataset name -> storage directory under the data root.
DATASET_DIRS = {
    tardis.INCREMENTAL_BOOK_L2: "book",
    tardis.BOOK_SNAPSHOT_25: "book_snapshot",
}

#: Output schema per design doc §3.2, minus the ``symbol``/``date`` partition keys, which
#: Hive partitioning carries in the path rather than the file.
SCHEMA = pa.schema(
    [
        # Kept rather than dropped as a constant: this is the only field anywhere in the
        # corpus that records which venue a row came from, and M1-T4's single-venue check
        # needs something data-derived to test. The vendor's URL shape serves every
        # exchange it carries, so a typo in the exchange segment yields a valid file from
        # the wrong venue -- which the design doc calls fatal to the result.
        ("exchange", pa.string()),
        ("timestamp", pa.int64()),
        ("local_timestamp", pa.int64()),
        ("latency_us", pa.int64()),
        ("is_snapshot", pa.bool_()),
        ("side", pa.string()),
        ("price", pa.float64()),
        ("quantity", pa.float64()),
    ]
)

#: Long form for the wide ``book_snapshot_25`` reference -- see :func:`normalise_snapshot`.
SNAPSHOT_SCHEMA = pa.schema(
    [
        ("exchange", pa.string()),
        ("timestamp", pa.int64()),
        ("local_timestamp", pa.int64()),
        ("latency_us", pa.int64()),
        ("side", pa.string()),
        ("level", pa.int16()),
        ("price", pa.float64()),
        ("quantity", pa.float64()),
    ]
)

SCHEMAS = {
    tardis.INCREMENTAL_BOOK_L2: SCHEMA,
    tardis.BOOK_SNAPSHOT_25: SNAPSHOT_SCHEMA,
}

SOURCE_COLUMNS = frozenset(
    {"exchange", "symbol", "timestamp", "local_timestamp", "is_snapshot", "side", "price", "amount"}
)

#: The snapshot dataset shares only these; its depth columns are matched by pattern.
SNAPSHOT_ID_COLUMNS = frozenset({"exchange", "symbol", "timestamp", "local_timestamp"})

_SNAPSHOT_COLUMN = re.compile(r"(asks|bids)\[(\d+)\]\.(price|amount)")

VALID_SIDES = frozenset({"bid", "ask"})

#: Melting turns one snapshot row into up to 50, so the read chunk has to shrink by the
#: same factor or the bounded-memory property is lost exactly where the files are largest.
SNAPSHOT_CHUNK_DIVISOR = 50


class BookDataError(RuntimeError):
    """Downloaded book data failed a structural check."""


@dataclass(frozen=True)
class IngestReport:
    """What one symbol-day of ingest actually contained."""

    symbol: str
    date: str
    dataset: str
    rows: int
    chunks: int
    snapshot_rows: int
    resync_events: int
    resync_rows: int
    removals: int
    path: Path

    def __str__(self) -> str:
        return (
            f"{self.symbol} {self.date} {self.dataset}: {self.rows:,} rows in "
            f"{self.chunks} chunk(s), {self.snapshot_rows:,} snapshot, "
            f"{self.removals:,} removals, {self.resync_events} resync(s) "
            f"covering {self.resync_rows:,} row(s)"
        )


def _parse_bool(values: pd.Series) -> pd.Series:
    """Coerce the vendor's ``is_snapshot`` column to real booleans.

    The CSV is read with ``dtype=str`` so numeric text survives intact, which makes this
    column the *strings* ``"true"``/``"false"`` -- and ``bool("false")`` is ``True``, so
    ``.astype(bool)`` would mark every row a snapshot. Identical trap to
    ``is_buyer_maker`` in :mod:`perpcarry.ingestion.fetch_trades`, kept local rather than
    shared because the two modules raise different errors and a premature abstraction
    across them would obscure both.
    """
    if values.dtype == bool:
        return values

    mapped = values.astype("string").str.strip().str.lower().map({"true": True, "false": False})
    if mapped.isna().any():
        bad = sorted(set(values[mapped.isna()].astype(str)))[:5]
        raise BookDataError(f"unparseable is_snapshot values: {bad}")
    return mapped.astype(bool)


def _check_symbol(raw: pd.DataFrame, symbol: str) -> None:
    symbols = set(raw["symbol"].astype("string").str.strip())
    if symbols != {symbol}:
        raise BookDataError(
            f"expected only {symbol} rows, found {sorted(symbols)[:5]} -- wrong file?"
        )


def _timestamps(raw: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Microsecond exchange and capture timestamps, as the vendor emits them."""
    return raw["timestamp"].astype("int64"), raw["local_timestamp"].astype("int64")


def _check_day(frame: pd.DataFrame, symbol: str, date: dt.date | str) -> pd.DataFrame:
    """Refuse rows from another UTC day.

    The whole file goes into one partition directory, so a stray row would be silently
    misfiled under this date rather than landing in its own.
    """
    expected = date.isoformat() if isinstance(date, dt.date) else str(date)
    days = pd.to_datetime(frame["timestamp"], unit="ms", utc=True).dt.strftime("%Y-%m-%d")
    stray = sorted(set(days[days != expected]))
    if stray:
        raise BookDataError(
            f"{symbol} {expected}: rows from {len(stray)} other UTC day(s) ({stray[:3]}); "
            "they would be misfiled into this date's partition"
        )
    return frame


def normalise(raw: pd.DataFrame, symbol: str, date: dt.date | str) -> pd.DataFrame:
    """Map one chunk of ``incremental_book_L2`` onto the §3.2 schema.

    ``timestamp`` and ``local_timestamp`` arrive in **microseconds** and are normalised to
    milliseconds to match every other dataset in §3. Their difference is the vendor's
    observed capture latency, computed from the raw microsecond values *before* the
    conversion and kept as ``latency_us`` (D-013).

    Measured on 0GUSDT 2026-06-01: p1 1.48 ms, median 2.04 ms, p99 516 ms -- so the
    latency is not sub-millisecond and converting first would not erase it outright, but
    **99.8% of rows are not a whole number of milliseconds**, so the microsecond detail
    would be lost on essentially every row. Keeping it costs one column.
    """
    missing = SOURCE_COLUMNS - set(raw.columns)
    if missing:
        raise BookDataError(f"vendor schema changed: missing columns {sorted(missing)}")

    if raw.empty:
        # An empty chunk is empty, not wrong: the content checks below would otherwise
        # report "no symbols found -- wrong file?", sending the reader after a URL bug
        # when the real answer is that the file has no rows. `ingest` decides what an
        # empty *file* means; a single empty chunk is not its business.
        return SCHEMA.empty_table().to_pandas()

    _check_symbol(raw, symbol)

    sides = raw["side"].astype("string").str.strip().str.lower()
    unknown = sorted(set(sides) - VALID_SIDES)
    if unknown:
        raise BookDataError(f"unknown side value(s) {unknown[:5]}, expected bid/ask")

    timestamp_us, local_us = _timestamps(raw)
    frame = pd.DataFrame(
        {
            "exchange": raw["exchange"].astype("string").str.strip(),
            "timestamp": timestamp_us // 1000,
            "local_timestamp": local_us // 1000,
            "latency_us": local_us - timestamp_us,
            "is_snapshot": _parse_bool(raw["is_snapshot"]),
            "side": sides,
            "price": raw["price"].astype("float64"),
            # amount == 0 is a level *removal* and must survive: see the module docstring.
            "quantity": raw["amount"].astype("float64"),
        }
    )
    return _check_day(frame, symbol, date)


def normalise_snapshot(raw: pd.DataFrame, symbol: str, date: dt.date | str) -> pd.DataFrame:
    """Map one chunk of ``book_snapshot_25`` onto the long reference schema.

    **This dataset is shaped nothing like the incremental feed**, which the spec did not
    say and which cost a failed run to discover: it is 104 *wide* columns -- one row per
    book image, with ``asks[0].price`` … ``bids[24].amount`` as separate columns -- not
    one row per level update.

    It is melted to one row per level (D-014) so it shares a vocabulary with every other
    dataset in §3, so M2-T2's "replayed top-25 match the reference" becomes a join rather
    than a reshape of 104 bracketed column names, and so DuckDB can query it without
    quoting every identifier.

    A book thinner than 25 levels leaves the trailing columns empty; those are dropped,
    because a level that does not exist is not a level with an unknown price. That is the
    opposite of the incremental feed's ``amount = 0``, which *is* meaningful -- there it
    marks a removal.
    """
    missing = SNAPSHOT_ID_COLUMNS - set(raw.columns)
    if missing:
        raise BookDataError(f"vendor schema changed: missing columns {sorted(missing)}")

    if raw.empty:
        return SNAPSHOT_SCHEMA.empty_table().to_pandas()

    _check_symbol(raw, symbol)

    levels = snapshot_depth(raw.columns)
    if not levels:
        raise BookDataError(
            "no asks[N].price / bids[N].amount columns found -- this does not look like "
            "a book_snapshot dataset"
        )

    timestamp_us, local_us = _timestamps(raw)
    base = pd.DataFrame(
        {
            "exchange": raw["exchange"].astype("string").str.strip(),
            "timestamp": timestamp_us // 1000,
            "local_timestamp": local_us // 1000,
            "latency_us": local_us - timestamp_us,
        }
    )

    pieces = []
    for side, prefix in (("ask", "asks"), ("bid", "bids")):
        for level in levels:
            price = pd.to_numeric(raw[f"{prefix}[{level}].price"], errors="coerce")
            amount = pd.to_numeric(raw[f"{prefix}[{level}].amount"], errors="coerce")
            present = price.notna() & amount.notna()
            if not present.any():
                continue
            piece = base[present].copy()
            piece["side"] = side
            piece["level"] = level
            piece["price"] = price[present].astype("float64")
            piece["quantity"] = amount[present].astype("float64")
            pieces.append(piece)

    if not pieces:
        return SNAPSHOT_SCHEMA.empty_table().to_pandas()

    frame = pd.concat(pieces, ignore_index=True)
    frame["level"] = frame["level"].astype("int16")
    frame["side"] = frame["side"].astype("string")
    frame = frame.sort_values(["timestamp", "side", "level"], ignore_index=True)
    return _check_day(frame[SNAPSHOT_SCHEMA.names], symbol, date)


def snapshot_depth(columns) -> list[int]:
    """Level indices present in a wide snapshot frame, ascending.

    Read from the columns rather than assumed to be 0..24: the dataset name says 25, but
    trusting a name over the file is how a silently truncated schema gets ingested.
    """
    levels = set()
    for column in columns:
        match = _SNAPSHOT_COLUMN.fullmatch(str(column))
        if match:
            levels.add(int(match.group(2)))
    return sorted(levels)


def iter_chunks(path: str | Path, *, chunksize: int = DEFAULT_CHUNKSIZE) -> Iterator[pd.DataFrame]:
    """Stream a gzipped vendor CSV in row chunks.

    Inflation happens lazily, so a truncated download raises ``EOFError`` partway through
    rather than yielding a short file that looks like a quiet trading day.
    """
    with gzip.open(path, "rb") as handle:
        yield from pd.read_csv(handle, chunksize=chunksize, dtype=str)


def partition_path(
    dataset: str, symbol: str, date: dt.date | str, root: Path | None = None
) -> Path:
    """Hive partition directory for one symbol-day."""
    day = date.isoformat() if isinstance(date, dt.date) else str(date)
    base = root if root is not None else data_root()
    return base / DATASET_DIRS[dataset] / f"symbol={symbol}" / f"date={day}"


def ingest(
    path: str | Path,
    symbol: str,
    date: dt.date,
    *,
    dataset: str = tardis.INCREMENTAL_BOOK_L2,
    root: Path | None = None,
    chunksize: int = DEFAULT_CHUNKSIZE,
) -> IngestReport:
    """Convert a downloaded vendor CSV into partitioned Parquet, streaming throughout.

    Writes row group by row group through a single :class:`pyarrow.parquet.ParquetWriter`
    rather than via :func:`perpcarry.storage.write_parquet`, which would materialise the
    whole day. One downloaded file is exactly one symbol-day, so the partition is fixed
    and can be written directly.

    Idempotent: the partition directory is replaced, not appended to, so re-running a day
    cannot silently double it.
    """
    if dataset not in SCHEMAS:
        raise ValueError(f"unknown dataset {dataset!r}, expected one of {list(SCHEMAS)}")
    is_incremental = dataset == tardis.INCREMENTAL_BOOK_L2
    schema = SCHEMAS[dataset]
    normaliser = normalise if is_incremental else normalise_snapshot
    if not is_incremental:
        chunksize = max(1, chunksize // SNAPSHOT_CHUNK_DIVISOR)

    dest_dir = partition_path(dataset, symbol, date, root)
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    dest_dir.mkdir(parents=True)
    dest = dest_dir / "part-0.parquet"

    rows = chunks = snapshot_rows = removals = 0
    resync_events = opening_rows = 0
    seen_non_snapshot = False
    prev_snapshot = True
    writer: pq.ParquetWriter | None = None

    try:
        for chunk in iter_chunks(path, chunksize=chunksize):
            frame = normaliser(chunk, symbol, date)
            if frame.empty:
                continue

            if not is_incremental:
                # Every row is a book image, so there is no opening-snapshot invariant to
                # check and no `amount = 0` removal convention to preserve.
                rows += len(frame)
                chunks += 1
                snapshot_rows += len(frame)
                opening_rows += len(frame)
                table = pa.Table.from_pandas(frame, schema=schema, preserve_index=False)
                if writer is None:
                    writer = pq.ParquetWriter(dest, schema, compression="zstd")
                writer.write_table(table)
                continue

            if chunks == 0 and not bool(frame["is_snapshot"].iloc[0]):
                raise BookDataError(
                    f"{symbol} {date}: file does not open with an is_snapshot block. "
                    "Replay has no initial state to build on, and this feed carries no "
                    "sequence number to recover from (§3.2)."
                )

            snapshot = frame["is_snapshot"].reset_index(drop=True)
            snapshot_rows += int(snapshot.sum())

            # A snapshot block after any diff is the vendor resyncing mid-day. Legitimate,
            # but M2's replayer must *reset* state there rather than apply the rows as
            # diffs -- so it is counted and reported, never silently smoothed over.
            #
            # Events, not rows: a resync is one ~1,400-row block, and reporting the rows
            # as the resync count reads as thousands of resets a day when the real figure
            # is around a dozen (measured: 0GUSDT 2026-06-01 has 13 events, 18,396 rows).
            # `prev_snapshot` starts True so the opening block, which has no preceding
            # diff, is never counted as an event.
            previous = snapshot.shift(1, fill_value=prev_snapshot)
            resync_events += int((snapshot & ~previous).sum())
            prev_snapshot = bool(snapshot.iloc[-1])

            if not seen_non_snapshot:
                if bool(snapshot.all()):
                    opening_rows += len(snapshot)
                else:
                    opening_rows += int(snapshot.idxmin())
                    seen_non_snapshot = True

            removals += int((frame["quantity"] == 0).sum())
            rows += len(frame)
            chunks += 1

            table = pa.Table.from_pandas(frame, schema=schema, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(dest, schema, compression="zstd")
            writer.write_table(table)
    except BaseException:
        if writer is not None:
            writer.close()
        # A half-written partition is worse than none: it looks like a thin day.
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise
    finally:
        if writer is not None:
            writer.close()

    if rows == 0:
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise BookDataError(f"{symbol} {date} {dataset}: no rows")

    return IngestReport(
        symbol=symbol,
        date=date.isoformat(),
        dataset=dataset,
        rows=rows,
        chunks=chunks,
        snapshot_rows=snapshot_rows,
        resync_events=resync_events,
        resync_rows=snapshot_rows - opening_rows,
        removals=removals,
        path=dest,
    )


def cache_path(dataset: str, symbol: str, date: dt.date) -> Path:
    """Where a downloaded vendor archive is cached.

    **The cache key must be built here, not left to** :func:`cached_fetch` **'s default.**
    That default is the URL's last path segment, which for this vendor is
    ``{SYMBOL}.csv.gz`` for *every date and every dataset* -- the date lives in the path,
    not the filename. Relying on it makes the cache collide across the entire backfill:
    the first day downloaded is served for all 24 months, and for both datasets. The
    Binance archive never exposed this because its filenames carry the date.
    """
    return cache_dir() / "tardis" / dataset / symbol / f"{date:%Y-%m-%d}.csv.gz"


def download(
    symbol: str,
    date: dt.date,
    *,
    dataset: str = tardis.INCREMENTAL_BOOK_L2,
    client: httpx.Client | None = None,
) -> Path:
    """Fetch one symbol-day archive, using the download cache.

    The vendor publishes no checksums, so ``cached_fetch`` runs without one and a cached
    file is trusted on presence. Corruption surfaces at inflation time instead.
    """
    url = tardis.dataset_url(dataset, symbol, date)
    try:
        return cached_fetch(url, dest=cache_path(dataset, symbol, date), client=client)
    except DownloadError as exc:
        if "401" in str(exc):
            raise tardis.FreeTierError(
                f"{url} returned 401. The free tier serves only the first day of each "
                "month; this is a tier limitation, not an authentication failure."
            ) from exc
        raise


def fetch_day(
    symbol: str,
    date: dt.date,
    *,
    datasets: tuple[str, ...] = tardis.DATASETS,
    root: Path | None = None,
    client: httpx.Client | None = None,
    chunksize: int = DEFAULT_CHUNKSIZE,
) -> list[IngestReport]:
    """Download and ingest one symbol-day of every requested dataset.

    Both are pulled together by default: ``book_snapshot_25`` is the only independent
    check on replay correctness this feed permits (there is no sequence number), and
    fetching it later would mean a second pass over the same months.
    """
    reports = []
    for dataset in datasets:
        path = download(symbol, date, dataset=dataset, client=client)
        report = ingest(path, symbol, date, dataset=dataset, root=root, chunksize=chunksize)
        log.info("%s", report)
        reports.append(report)
    return reports


def backfill(
    symbol: str,
    start: dt.date,
    end: dt.date,
    *,
    datasets: tuple[str, ...] = tardis.DATASETS,
    root: Path | None = None,
    client: httpx.Client | None = None,
    chunksize: int = DEFAULT_CHUNKSIZE,
    allow_missing: bool = False,
) -> tuple[list[IngestReport], list[dt.date]]:
    """Ingest every free-tier day in ``[start, end]``. Returns reports and skipped days.

    A missing day is only skipped when ``allow_missing`` is set -- a symbol listed
    mid-window legitimately has no earlier book data, but an explainable gap still has to
    be acknowledged rather than absorbed. Skipped days feed M1-T4's allowlist.
    """
    reports: list[IngestReport] = []
    skipped: list[dt.date] = []

    for day in tardis.free_tier_days(start, end):
        try:
            reports.extend(
                fetch_day(
                    symbol,
                    day,
                    datasets=datasets,
                    root=root,
                    client=client,
                    chunksize=chunksize,
                )
            )
        except DownloadError:
            if not allow_missing:
                raise
            log.warning("no book data for %s %s -- skipping", symbol, day)
            skipped.append(day)
    return reports, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download historical L2 order book data")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start", required=True, type=dt.date.fromisoformat)
    parser.add_argument("--end", required=True, type=dt.date.fromisoformat)
    parser.add_argument(
        "--dataset",
        action="append",
        choices=list(tardis.DATASETS),
        help="repeatable; defaults to both",
    )
    parser.add_argument("--chunksize", type=int, default=DEFAULT_CHUNKSIZE)
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="skip days with no data (e.g. before the symbol was listed)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    reports, skipped = backfill(
        args.symbol,
        args.start,
        args.end,
        datasets=tuple(args.dataset) if args.dataset else tardis.DATASETS,
        chunksize=args.chunksize,
        allow_missing=args.allow_missing,
    )
    log.info("ingested %d symbol-day dataset(s)", len(reports))
    if skipped:
        log.warning("skipped %d day(s): %s", len(skipped), [d.isoformat() for d in skipped])
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
