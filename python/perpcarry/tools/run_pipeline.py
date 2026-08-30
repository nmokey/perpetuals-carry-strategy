"""Replay one symbol-day through the assembled pipeline and record the checkpoint (M3-T3).

    uv run python -m perpcarry.tools.run_pipeline --symbol 0GUSDT --date 2026-06-01

Parquet -> PyArrow batch -> pybind11 -> ``Pipeline`` (ingest thread -> SPSC queue -> replay
thread). One crossing of the Python/C++ boundary per batch, never per event (Risk R4).

**Licence.** The input is raw vendor book data (Tardis Clause 9.2(2)): it must never be
committed or reach CI. The output written here is counts plus a SHA-256 of the final book's
``dump_csv`` -- a digest exposes no levels and cannot reconstruct a book, which is what
makes it publishable where the dump itself is not.

The checkpoint this compares against is the committed M2-T2 summary for the same symbol-day.
The design doc's "final state matches M2-T2 checkpoint" named an artifact that had never
existed; the M3-T3 spec defines it as those counts plus the digest.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import time
from pathlib import Path

import perpcarry_cpp

from perpcarry.ingestion import tardis_archive as tardis
from perpcarry.tools import export_book

#: Columns the replay needs, in the order ``BookUpdate`` takes them. Taken from the
#: exporter rather than restated: a second copy of a column list is a second source of
#: truth that can only ever agree by luck (C15).
EVENT_COLUMNS = export_book.EVENT_COLUMNS

DEFAULT_BATCH_SIZE = 1_000_000


class PipelineRunError(RuntimeError):
    """Raised when the run cannot be performed or its checkpoint cannot be evaluated."""


def _side(value: str) -> perpcarry_cpp.Side:
    if value == "bid":
        return perpcarry_cpp.Side.Bid
    if value == "ask":
        return perpcarry_cpp.Side.Ask
    raise PipelineRunError(f"unknown side {value!r}, expected bid or ask")


def _updates(batch) -> list[perpcarry_cpp.BookUpdate]:
    """Convert one PyArrow record batch to the extension's row type.

    Column-at-a-time rather than row-at-a-time: ``to_pylist`` on the whole batch builds a
    dict per row, which dominates the cost of the run for no benefit.
    """
    timestamps = batch.column("timestamp").to_pylist()
    local = batch.column("local_timestamp").to_pylist()
    snapshots = batch.column("is_snapshot").to_pylist()
    sides = batch.column("side").to_pylist()
    prices = batch.column("price").to_pylist()
    quantities = batch.column("quantity").to_pylist()
    return [
        perpcarry_cpp.BookUpdate(
            timestamp=timestamps[i],
            local_timestamp=local[i],
            is_snapshot=snapshots[i],
            side=_side(sides[i]),
            price=prices[i],
            quantity=quantities[i],
        )
        for i in range(batch.num_rows)
    ]


def checkpoint_digest(book: perpcarry_cpp.OrderBook, depth: int = 25) -> str:
    """SHA-256 of the C++ rendering of the book's top ``depth`` levels.

    Rendered on the C++ side so there is exactly one canonical serialisation. Re-deriving it
    in Python would agree today -- ``repr(float)`` and ``std::to_chars`` both produce
    shortest round-trip text -- and that coincidence is precisely what C15 warns is
    invisible until it stops holding.
    """
    return hashlib.sha256(perpcarry_cpp.dump_csv(book, depth).encode()).hexdigest()


def m2_t2_summary(symbol: str, date: str) -> dict | None:
    """The committed M2-T2 result for this symbol-day, if one exists."""
    path = Path(__file__).resolve().parents[3] / "docs" / "validation"
    candidate = path / f"M2-T2-{symbol}-{date}.json"
    if not candidate.exists():
        return None
    return json.loads(candidate.read_text())


def run(
    symbol: str,
    date: dt.date | str,
    *,
    root: Path | None = None,
    queue_capacity: int = 65536,
    batch_size: int = DEFAULT_BATCH_SIZE,
    depth: int = 25,
) -> dict:
    day = dt.date.fromisoformat(date) if isinstance(date, str) else date
    files = export_book._partition_files(tardis.INCREMENTAL_BOOK_L2, symbol, day, root)

    pipeline = perpcarry_cpp.Pipeline(queue_capacity=queue_capacity)
    consumed = 0
    peak_occupancy = 0
    producer_stalls = 0
    started = time.perf_counter()

    for batch in export_book._iter_batches(files, EVENT_COLUMNS, batch_size):
        result = pipeline.run(_updates(batch))
        consumed += result.consumed
        peak_occupancy = max(peak_occupancy, result.peak_queue_occupancy)
        producer_stalls += result.producer_stalls

    elapsed = time.perf_counter() - started
    stats = pipeline.stats()
    book = pipeline.book()

    report = {
        "task": "M3-T3",
        "symbol": symbol,
        "date": day.isoformat(),
        "produced_by": (
            "perpcarry.tools.run_pipeline, at the commit that introduces this file "
            "(see docs/specs/M3/M3-T3-pipeline-smoke-test.md); re-run to reproduce"
        ),
        "queue_capacity": queue_capacity,
        "batch_size": batch_size,
        "depth": depth,
        "events": consumed,
        "seconds": round(elapsed, 3),
        "peak_queue_occupancy": peak_occupancy,
        "producer_stalls": producer_stalls,
        "replay": {
            "applied": stats.applied,
            "snapshot_rows": stats.snapshot_rows,
            "resyncs": stats.resyncs,
            "removals": stats.removals,
            "crossed": stats.crossed,
            "last_timestamp": stats.last_timestamp,
        },
        "final_book": {
            "bid_levels": book.level_count(perpcarry_cpp.Side.Bid),
            "ask_levels": book.level_count(perpcarry_cpp.Side.Ask),
            "top_25_sha256": checkpoint_digest(book, depth),
        },
    }

    # The checkpoint half of the criterion: the same events the M2-T2 harness counted.
    reference = m2_t2_summary(symbol, day.isoformat())
    if reference is None:
        report["checkpoint"] = "no committed M2-T2 summary for this symbol-day"
    elif reference.get("coverage") != "full day":
        report["checkpoint"] = (
            f"M2-T2 summary covers {reference.get('coverage')!r}, not the full day, so its "
            "event count is not comparable with a full-day pipeline run"
        )
    else:
        expected = reference["events"]
        report["checkpoint"] = "matches M2-T2" if consumed == expected else "DIVERGED from M2-T2"
        report["checkpoint_expected_events"] = expected
        if consumed != expected:
            raise PipelineRunError(
                f"pipeline consumed {consumed} events, M2-T2 recorded {expected} for the "
                f"same symbol-day: the pipeline and the validated replay disagree"
            )

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--queue-capacity", type=int, default=65536)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--out", type=Path, help="write the JSON report here as well")
    args = parser.parse_args(argv)

    try:
        report = run(
            args.symbol,
            args.date,
            queue_capacity=args.queue_capacity,
            batch_size=args.batch_size,
        )
    except (PipelineRunError, export_book.ExportError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    text = json.dumps(report, indent=2) + "\n"
    print(text, end="")
    if args.out is not None:
        args.out.write_text(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
