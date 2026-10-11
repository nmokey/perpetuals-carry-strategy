"""Book partition discovery using the writer's layout; no CSV export or CLI dependency."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from perpcarry.ingestion import fetch_book

# Shared order for stored events, replay batches and validator CSV headers. The C++
# validator checks its header exactly; changing this contract must fail visibly.
EVENT_COLUMNS = ["timestamp", "local_timestamp", "is_snapshot", "side", "price", "quantity"]


class BookPartitionError(RuntimeError):
    """The requested book partition is unavailable."""


def partition_files(
    dataset: str, symbol: str, date: dt.date, root: Path | None = None
) -> list[Path]:
    """Locate a partition through the writer's own path helper, never a restated layout.

    Restating where ``fetch_book`` puts things is how M1-T4 shipped a validator that
    looked in a directory which had never existed and reported the corpus healthy (C15).
    """
    directory = fetch_book.partition_path(dataset, symbol, date, root)
    files = sorted(directory.glob("*.parquet"))
    if not files:
        raise BookPartitionError(f"no {dataset} partition for {symbol} {date} at {directory}")
    return files
