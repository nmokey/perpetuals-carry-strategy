"""Batch adapter for Python book storage and the deterministic C++ replay boundary."""

from __future__ import annotations

import perpcarry_cpp
import pyarrow as pa


class ReplayInputError(RuntimeError):
    """Raised when the run cannot be performed or its checkpoint cannot be evaluated."""


def _side(value: str) -> perpcarry_cpp.Side:
    if value == "bid":
        return perpcarry_cpp.Side.Bid
    if value == "ask":
        return perpcarry_cpp.Side.Ask
    raise ReplayInputError(f"unknown side {value!r}, expected bid or ask")


def updates_from_batch(batch: pa.RecordBatch) -> list[perpcarry_cpp.BookUpdate]:
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
