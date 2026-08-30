"""M3-T3 acceptance: the assembled pipeline, end to end.

Spec: docs/specs/M3/M3-T3-pipeline-smoke-test.md.

Parquet -> PyArrow batch -> pybind11 -> BookReplayer -> SPSCQueue -> consumer, with the
queue on the C++ side of the boundary between ingest and replay. These tests run on
synthetic input: vendor book rows may never reach CI (Tardis Clause 9.2(2)), so the real
symbol-day run is local and its result is recorded in docs/validation/.

The criterion is "completes without error; final state matches M2-T2 checkpoint". The
checkpoint had never been defined -- M2-T2 emits an aggregated JSON summary and never
serialises book state -- so the M3-T3 spec defines it as the committed JSON counts plus a
SHA-256 of ``dump_csv``. The dump is pure and deterministic, so the digest is stable; and a
digest is publishable where the dump plainly is not.
"""

from __future__ import annotations

import hashlib

import perpcarry_cpp
import pytest


def digest(book: perpcarry_cpp.OrderBook, depth: int = 25) -> str:
    """The checkpoint. Rendered by the C++ side so there is one canonical serialisation."""
    return hashlib.sha256(perpcarry_cpp.dump_csv(book, depth).encode()).hexdigest()


def synthetic_day(levels: int = 50, updates: int = 20_000) -> list[perpcarry_cpp.BookUpdate]:
    """An opening snapshot followed by deterministic diffs.

    Deterministic by construction rather than by seed: the point is that two runs over the
    same list must agree, so the list must not vary.
    """
    batch = [
        perpcarry_cpp.BookUpdate(
            timestamp=1000,
            local_timestamp=1000,
            is_snapshot=True,
            side=side,
            price=base + i * 0.1,
            quantity=1.0 + i,
        )
        for side, base in ((perpcarry_cpp.Side.Bid, 100.0), (perpcarry_cpp.Side.Ask, 200.0))
        for i in range(levels)
    ]
    for n in range(updates):
        side = perpcarry_cpp.Side.Bid if n % 2 == 0 else perpcarry_cpp.Side.Ask
        base = 100.0 if side == perpcarry_cpp.Side.Bid else 200.0
        batch.append(
            perpcarry_cpp.BookUpdate(
                timestamp=1001 + n,
                local_timestamp=1001 + n,
                is_snapshot=False,
                side=side,
                price=base + (n % levels) * 0.1,
                # Every 17th update removes the level, so the removal path is exercised too.
                quantity=0.0 if n % 17 == 0 else 1.0 + (n % 9),
            )
        )
    return batch


def single_threaded(batch: list[perpcarry_cpp.BookUpdate]) -> perpcarry_cpp.BookReplayer:
    replayer = perpcarry_cpp.BookReplayer()
    replayer.apply_batch(batch)
    return replayer


def test_the_pipeline_completes_and_consumes_everything():
    """M3-T3 tests 1 and 2."""
    batch = synthetic_day()
    pipeline = perpcarry_cpp.Pipeline()

    result = pipeline.run(batch)

    assert result.consumed == len(batch)
    assert result.replay.applied == len(batch)
    assert pipeline.stats().applied == len(batch)


def test_threading_changes_timing_never_results():
    """M3-T3 test 3 -- the one that would catch a real regression.

    If threading changed the result at all, the number it changed would eventually be a fill
    price, and nothing downstream could tell. Compared through ``dump_csv`` rather than a
    few spot values, so the whole top of the book has to agree.
    """
    batch = synthetic_day()

    pipeline = perpcarry_cpp.Pipeline()
    pipeline.run(batch)
    reference = single_threaded(batch)

    assert digest(pipeline.book()) == digest(reference.book())
    assert pipeline.stats().applied == reference.stats().applied
    assert pipeline.stats().removals == reference.stats().removals
    assert pipeline.stats().crossed == reference.stats().crossed


def test_the_same_input_produces_the_same_digest():
    """M3-T3 test 4 -- determinism across runs, not merely within one (D-020)."""
    batch = synthetic_day()

    first = perpcarry_cpp.Pipeline()
    first.run(batch)
    second = perpcarry_cpp.Pipeline(queue_capacity=64)  # a different queue, same answer
    second.run(batch)

    assert digest(first.book()) == digest(second.book())


def test_the_queue_actually_filled():
    """M3-T3 test 5 -- the C15 guard.

    The obvious way for this whole task to pass while testing nothing: a consumer that keeps
    up so easily the queue is always empty. Then the pipeline is a loop with extra steps and
    the concurrency was never exercised. A deliberately tiny queue against a real workload
    forces the contention this task exists to cover.
    """
    batch = synthetic_day()
    pipeline = perpcarry_cpp.Pipeline(queue_capacity=8)

    result = pipeline.run(batch)

    assert result.queue_capacity == 8
    assert result.peak_queue_occupancy > 0, "the queue was never occupied; nothing was tested"
    assert result.producer_stalls > 0, "the producer never had to wait; there was no contention"


def test_a_replay_error_surfaces_instead_of_hanging():
    """M3-T3 test 6.

    The consumer runs the replay, so it is the side that throws. If that were swallowed the
    run would report success on a corrupt book; if the producer were left waiting on a queue
    nobody drains, the failure would be a hang -- worse than an exception, because a hang
    carries no message.
    """
    # No opening snapshot: this feed carries no sequence number and cannot start mid-stream.
    batch = [
        perpcarry_cpp.BookUpdate(
            timestamp=1000, side=perpcarry_cpp.Side.Bid, price=100.0, quantity=1.0
        )
    ]

    with pytest.raises(perpcarry_cpp.BookReplayError):
        perpcarry_cpp.Pipeline().run(batch)


def test_a_replay_error_deep_in_a_full_queue_still_surfaces():
    """The same failure, but with the producer far ahead and the queue saturated.

    This is the case that deadlocks if the consumer forgets to tell the producer it has
    stopped: thousands of items still queued, a producer blocked on a full ring, and nothing
    left to drain it.
    """
    batch = synthetic_day(updates=50_000)
    # A backwards timestamp partway through: the replayer rejects it, mid-stream, while the
    # producer is still pushing.
    batch[30_000] = perpcarry_cpp.BookUpdate(
        timestamp=1, side=perpcarry_cpp.Side.Bid, price=100.0, quantity=1.0
    )

    with pytest.raises(perpcarry_cpp.BookReplayError):
        perpcarry_cpp.Pipeline(queue_capacity=8).run(batch)
