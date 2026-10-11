"""Export one symbol-day of book data to CSV for the M2-T2 replay validator.

Why this exists (D-018). M2-T2's acceptance criterion compares replayed state against the
vendor's ``book_snapshot_25``, but the C++ core does no file I/O (D-012) and the Python
bindings that would feed it are M3-T1 -- which *depends on* M2-T2. This exporter plus the
``perpcarry_replay_validate`` tool close that loop without inverting the dependency.

**Licence.** The output is raw vendor book rows, which Tardis Clause 9.2(2) forbids
redistributing: it must never be committed, uploaded, or allowed into CI. Output therefore
defaults under the data root, which is gitignored (C9). Only the validator's aggregated
JSON summary is publishable.

Size, measured 2026-08-20: a full ``BTCUSDT`` book day is 161M events and 115M reference
rows, which is roughly 15 GB of CSV -- more than the free disk on this machine. Use
``--max-events`` to validate a prefix of the day; the reference is truncated to match, so
the comparison set stays consistent.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.csv as pa_csv

from perpcarry import storage
from perpcarry.ingestion import fetch_book
from perpcarry.ingestion import tardis_archive as tardis
from perpcarry.ingestion.book_partitions import (
    EVENT_COLUMNS,
    partition_files,
)
from perpcarry.ingestion.book_partitions import (
    BookPartitionError as ExportError,
)
from perpcarry.storage import iter_parquet_batches

#: Column order written to the reference CSV.
REFERENCE_COLUMNS = ["timestamp", "side", "level", "price", "quantity"]

DEFAULT_BATCH_SIZE = 1_000_000


@dataclass(frozen=True)
class ExportReport:
    """What one export actually contained."""

    symbol: str
    date: str
    events_path: Path
    reference_path: Path
    events: int
    reference_rows: int
    images: int
    last_timestamp: int
    truncated: bool

    def __str__(self) -> str:
        suffix = " (truncated)" if self.truncated else ""
        return (
            f"{self.symbol} {self.date}: {self.events:,} events{suffix}, "
            f"{self.reference_rows:,} reference rows in {self.images:,} images\n"
            f"  {self.events_path}\n  {self.reference_path}"
        )


def _resolve_out_dir(symbol: str, date: str, root: Path | None, out_dir: Path | None) -> Path:
    """Default under the data root, so the licence rule holds by construction, not by care."""
    if out_dir is not None:
        return Path(out_dir)
    base = storage.data_root() if root is None else Path(root)
    return base / "validation" / f"symbol={symbol}" / f"date={date}"


def export(
    symbol: str,
    date: dt.date | str,
    *,
    root: Path | None = None,
    out_dir: Path | None = None,
    max_events: int | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> ExportReport:
    """Write ``events.csv`` and ``reference.csv`` for one symbol-day."""
    day = dt.date.fromisoformat(date) if isinstance(date, str) else date
    iso = day.isoformat()
    destination = _resolve_out_dir(symbol, iso, root, out_dir)
    destination.mkdir(parents=True, exist_ok=True)

    events_path = destination / "events.csv"
    reference_path = destination / "reference.csv"

    event_files = partition_files(tardis.INCREMENTAL_BOOK_L2, symbol, day, root)
    reference_files = partition_files(tardis.BOOK_SNAPSHOT_25, symbol, day, root)

    events = 0
    last_timestamp = 0
    truncated = False
    event_schema = pa.schema([(name, fetch_book.SCHEMA.field(name).type) for name in EVENT_COLUMNS])

    # `--max-events` must not cut in the middle of a millisecond.
    #
    # The vendor emits a reference image once the whole group of updates sharing an
    # exchange millisecond has been applied. Stopping mid-group therefore leaves the final
    # image describing a book strictly ahead of the replayed one, and it mismatches every
    # time -- observed on BTCUSDT 2026-06-01, where a cut at exactly 20,000,000 events
    # landed inside a 150-event millisecond and produced one guaranteed failure that looked
    # exactly like a replay defect. So the budget is a floor, and the export runs on to the
    # end of the millisecond it lands in.
    budget_end: int | None = None

    with pa_csv.CSVWriter(events_path, event_schema) as writer:
        for batch in iter_parquet_batches(event_files, EVENT_COLUMNS, batch_size):
            timestamps = batch.column("timestamp").to_pylist()

            over_budget = max_events is not None and events + len(timestamps) > max_events
            if budget_end is None and over_budget:
                cut = max_events - events
                budget_end = timestamps[cut - 1] if cut > 0 else last_timestamp
                truncated = True

            if budget_end is not None:
                keep = len(timestamps)
                for index, value in enumerate(timestamps):
                    if value > budget_end:
                        keep = index
                        break
                exhausted = keep < len(timestamps)
                if keep == 0:
                    break
                batch = batch.slice(0, keep)
                timestamps = timestamps[:keep]
            else:
                exhausted = False

            writer.write_table(pa.Table.from_batches([batch], schema=event_schema))
            events += batch.num_rows
            last_timestamp = timestamps[-1]

            if exhausted:
                break

    if events == 0:
        raise ExportError(f"{symbol} {iso}: the events partition is empty")

    reference_rows = 0
    images = 0
    previous_timestamp: int | None = None
    reference_schema = pa.schema(
        [(name, fetch_book.SNAPSHOT_SCHEMA.field(name).type) for name in REFERENCE_COLUMNS]
    )

    with pa_csv.CSVWriter(reference_path, reference_schema) as writer:
        for batch in iter_parquet_batches(reference_files, REFERENCE_COLUMNS, batch_size):
            timestamps = batch.column("timestamp").to_pylist()
            # The reference is sorted by timestamp on ingest (D-014), so once it passes the
            # last exported event there is nothing further that can be compared.
            keep = len(timestamps)
            for index, value in enumerate(timestamps):
                if value > last_timestamp:
                    keep = index
                    break
            # Decided before the slice: afterwards `keep == len(timestamps)` always, and
            # the stop condition would silently never fire.
            exhausted = keep < len(timestamps)
            if keep == 0:
                break

            batch = batch.slice(0, keep)
            timestamps = timestamps[:keep]
            writer.write_table(pa.Table.from_batches([batch], schema=reference_schema))
            reference_rows += batch.num_rows
            for value in timestamps:
                if value != previous_timestamp:
                    images += 1
                    previous_timestamp = value

            if exhausted:
                break

    return ExportReport(
        symbol=symbol,
        date=iso,
        events_path=events_path,
        reference_path=reference_path,
        events=events,
        reference_rows=reference_rows,
        images=images,
        last_timestamp=last_timestamp,
        truncated=truncated,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument(
        "--max-events",
        type=int,
        default=None,
        help="stop after N events and truncate the reference to match; a full BTCUSDT day "
        "is ~15 GB of CSV",
    )
    args = parser.parse_args(argv)

    try:
        report = export(args.symbol, args.date, out_dir=args.out_dir, max_events=args.max_events)
    except ExportError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(report)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
