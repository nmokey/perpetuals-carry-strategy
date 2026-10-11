"""M3-T3: checkpoint/report orchestration; synthetic fixtures only.

Batch adapter checks live in tests/test_replay.py; C++ queue replay is covered by
tests/test_pipeline.py. These tool tests cover reproducible digests and missing summaries.
"""

from __future__ import annotations

import perpcarry_cpp
import pytest

from perpcarry.tools import run_pipeline


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
