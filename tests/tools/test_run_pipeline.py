"""M3-T3 -- the pipeline runner's Python half.

Spec: docs/specs/M3/M3-T3-pipeline-smoke-test.md.

Every fixture is synthetic: the vendor's terms forbid book rows entering the repository
(Tardis Clause 9.2(2), convention C9).

The threaded replay itself is covered in ``tests/test_pipeline.py``. What is left here is
the part that only exists in Python -- turning an Arrow batch into the extension's row type
-- and it is worth its own test for an unglamorous reason: a swapped column mapping produces
a run that completes, reports the right event count, and builds an entirely wrong book. No
count check anywhere in this project would notice.
"""

from __future__ import annotations

import perpcarry_cpp
import pyarrow as pa
import pytest

from perpcarry.tools import run_pipeline


def make_batch(rows: list[dict]) -> pa.RecordBatch:
    """Build a batch with the exporter's own column list, never a restated one (C15)."""
    columns = {name: [row[name] for row in rows] for name in run_pipeline.EVENT_COLUMNS}
    return pa.RecordBatch.from_pydict(columns)


def test_every_column_lands_in_the_field_it_belongs_to():
    batch = make_batch(
        [
            {
                "timestamp": 1000,
                "local_timestamp": 1002,
                "is_snapshot": True,
                "side": "bid",
                "price": 100.5,
                "quantity": 4.25,
            },
            {
                "timestamp": 1001,
                "local_timestamp": 1003,
                "is_snapshot": False,
                "side": "ask",
                "price": 101.5,
                "quantity": 7.75,
            },
        ]
    )

    updates = run_pipeline._updates(batch)

    assert len(updates) == 2
    first, second = updates
    # Asserted field by field, with every value distinct, so a transposition of any two
    # columns fails rather than cancelling out.
    assert first.timestamp == 1000
    assert first.local_timestamp == 1002
    assert first.is_snapshot is True
    assert first.side == perpcarry_cpp.Side.Bid
    assert first.price == 100.5
    assert first.quantity == 4.25

    assert second.timestamp == 1001
    assert second.local_timestamp == 1003
    assert second.is_snapshot is False
    assert second.side == perpcarry_cpp.Side.Ask
    assert second.price == 101.5
    assert second.quantity == 7.75


def test_an_unknown_side_is_rejected_rather_than_defaulted():
    """A silent default would put every unrecognised row on the bid side."""
    batch = make_batch(
        [
            {
                "timestamp": 1000,
                "local_timestamp": 1000,
                "is_snapshot": True,
                "side": "buy",  # the archive's word, not this feed's
                "price": 100.0,
                "quantity": 1.0,
            }
        ]
    )

    with pytest.raises(run_pipeline.PipelineRunError, match="unknown side"):
        run_pipeline._updates(batch)


def test_the_checkpoint_digest_is_stable_and_depth_sensitive():
    book = perpcarry_cpp.OrderBook()
    for i in range(40):
        book.apply(perpcarry_cpp.Side.Bid, 100.0 - i * 0.1, 1.0 + i)
        book.apply(perpcarry_cpp.Side.Ask, 101.0 + i * 0.1, 2.0 + i)

    assert run_pipeline.checkpoint_digest(book) == run_pipeline.checkpoint_digest(book)
    # A digest that ignored depth would silently compare different amounts of book between
    # a run and its checkpoint.
    assert run_pipeline.checkpoint_digest(book, 25) != run_pipeline.checkpoint_digest(book, 10)


def test_a_changed_level_changes_the_digest():
    """Otherwise the checkpoint would pass for a book it should reject."""
    book = perpcarry_cpp.OrderBook()
    book.apply(perpcarry_cpp.Side.Bid, 100.0, 4.0)
    book.apply(perpcarry_cpp.Side.Ask, 101.0, 7.0)
    before = run_pipeline.checkpoint_digest(book)

    book.apply(perpcarry_cpp.Side.Bid, 100.0, 4.5)

    assert run_pipeline.checkpoint_digest(book) != before


def test_the_committed_m2_t2_summary_is_found_where_the_runner_looks():
    """The path is computed from this file's location, which is exactly the kind of restated
    layout C15 is about -- so it gets asserted rather than assumed."""
    summary = run_pipeline.m2_t2_summary("0GUSDT", "2026-06-01")

    assert summary is not None, "the committed M2-T2 summary was not found"
    assert summary["symbol"] == "0GUSDT"
    assert summary["verdict"] == "pass"
    assert run_pipeline.m2_t2_summary("NOSUCHSYMBOL", "2026-06-01") is None


def test_a_missing_validation_directory_raises_rather_than_reporting_no_summary(monkeypatch):
    """The two failure modes must not collapse into one.

    ``m2_t2_summary`` finds the directory relative to its own source file, which holds for a
    source checkout and not for an installed wheel. If a missing directory returned ``None``
    like a missing summary does, the checkpoint comparison would be skipped and the run would
    report success having compared nothing (C15).
    """
    monkeypatch.setattr(run_pipeline, "__file__", "/nonexistent/a/b/c/run_pipeline.py")

    with pytest.raises(run_pipeline.PipelineRunError, match="no validation directory"):
        run_pipeline.m2_t2_summary("0GUSDT", "2026-06-01")
