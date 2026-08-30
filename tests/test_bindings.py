"""M3-T1 acceptance: the pybind11 boundary is faithful.

Spec: docs/specs/M3/M3-T1-pybind11-bindings.md.

**These tests are not about whether the book is correct.** That is settled by 51 C++ tests,
including a 100k-operation differential run against an independent ``std::map`` oracle.
Restating those assertions in Python would be one assumption written twice, agreeing by
construction rather than by evidence -- the C15 failure that let ``validate_data`` report a
healthy corpus while looking in a directory that had never existed.

What no C++ test can see is the boundary itself: whether ordering survives, whether a float
is still the same float, whether a returned view outlives the thing it points into, and
whether an error crosses as an exception or as a silent zero. That is what is tested here,
and every expected value is derived from the input this file supplies rather than copied
from a C++ fixture.
"""

from __future__ import annotations

import perpcarry_cpp
import pytest

# The full public surface. Pinned so that binding a new symbol is a deliberate act with a
# failing test attached, rather than something that happens because the C++ function existed
# and was easy to reach. Cheap, and it guards a boundary that is much easier to keep small
# than to shrink later (C14).
EXPECTED_SYMBOLS = {
    "BookReplayError",
    "BookReplayer",
    "BookUpdate",
    "OrderBook",
    "ReplayStats",
    "Side",
    "version",
}

# One side of a small book, defined here and used to derive every expectation below.
BIDS = [(100.0, 4.0), (99.5, 6.0), (99.0, 2.5)]
ASKS = [(101.0, 7.0), (102.0, 8.0)]


def build_book() -> perpcarry_cpp.OrderBook:
    book = perpcarry_cpp.OrderBook()
    for price, quantity in BIDS:
        book.apply(perpcarry_cpp.Side.Bid, price, quantity)
    for price, quantity in ASKS:
        book.apply(perpcarry_cpp.Side.Ask, price, quantity)
    return book


def snapshot_batch() -> list[perpcarry_cpp.BookUpdate]:
    """A valid opening batch: the replayer rejects a stream that does not start with one."""
    return [
        perpcarry_cpp.BookUpdate(
            timestamp=1000,
            local_timestamp=1002,
            is_snapshot=True,
            side=side,
            price=price,
            quantity=quantity,
        )
        for side, levels in (
            (perpcarry_cpp.Side.Bid, BIDS),
            (perpcarry_cpp.Side.Ask, ASKS),
        )
        for price, quantity in levels
    ]


def test_extension_is_a_top_level_module():
    """M3-T1 test 1 -- installed top-level, not nested inside the pure-Python package.

    The M0 acceptance criterion names this explicitly, and it is invisible from the C++
    side: a wheel that installed it as ``perpcarry.perpcarry_cpp`` would still pass every
    Catch2 test.
    """
    import perpcarry

    assert perpcarry_cpp.__name__ == "perpcarry_cpp"
    assert not hasattr(perpcarry, "perpcarry_cpp")


def test_public_surface_is_exactly_what_the_spec_names():
    """M3-T1 test 9."""
    actual = {name for name in dir(perpcarry_cpp) if not name.startswith("_")}
    assert actual == EXPECTED_SYMBOLS


def test_book_state_matches_what_the_input_implies():
    """M3-T1 test 2 -- expectations derived from BIDS/ASKS, not retyped from a C++ test."""
    book = build_book()

    assert book.best_bid() == max(BIDS)
    assert book.best_ask() == min(ASKS)
    assert book.level_count(perpcarry_cpp.Side.Bid) == len(BIDS)
    assert book.level_count(perpcarry_cpp.Side.Ask) == len(ASKS)
    assert book.is_crossed() is False
    assert book.best(perpcarry_cpp.Side.Bid) == book.best_bid()


def test_empty_book_reports_no_best_rather_than_a_sentinel():
    """A zero or a 0.0 price crossing as "no bid" would be a silently wrong number."""
    book = perpcarry_cpp.OrderBook()

    assert book.best_bid() is None
    assert book.best_ask() is None
    assert book.levels(perpcarry_cpp.Side.Bid) == []


def test_levels_cross_ordered_best_to_worst_on_both_sides():
    """M3-T1 test 3 -- bids descending, asks ascending."""
    book = build_book()

    assert book.levels(perpcarry_cpp.Side.Bid) == sorted(BIDS, reverse=True)
    assert book.levels(perpcarry_cpp.Side.Ask) == sorted(ASKS)


@pytest.mark.parametrize(
    "value",
    [
        0.4191,  # not exactly representable in binary
        0.1 + 0.2,  # 0.30000000000000004 -- 17 significant digits
        12345678.901234567,
        1e-9,
        1.2345678901e-05,
    ],
)
def test_prices_and_quantities_survive_the_round_trip_bit_exactly(value):
    """M3-T1 test 4.

    A float that changes crossing the boundary makes every downstream number wrong while
    looking entirely plausible -- there is no error, just a slightly different fill price.
    """
    book = perpcarry_cpp.OrderBook()
    book.apply(perpcarry_cpp.Side.Bid, value, value)

    # Both emitting paths, because they are separate code. Asserting only through
    # best_bid() left a float32 narrowing inside levels() alive under mutation -- and
    # levels() is the path M5 walks for depth, so it is the one that matters more.
    price, quantity = book.best_bid()
    assert price == value
    assert quantity == value

    ((levels_price, levels_quantity),) = book.levels(perpcarry_cpp.Side.Bid)
    assert levels_price == value
    assert levels_quantity == value

    # repr comparison catches a value that compares equal but was rebuilt through a
    # lower-precision path.
    assert repr(price) == repr(value)
    assert repr(levels_price) == repr(value)


def test_levels_is_a_copy_not_a_view_into_the_book():
    """M3-T1 test 5 -- the task's one real hazard.

    ``OrderBook::levels()`` returns a span its own header documents as invalidated by the
    next ``apply()``. Exposed as a view this would keep returning numbers after the book
    moved on, and they would be garbage -- surfacing as a plausible fill price rather than
    as a crash.
    """
    book = build_book()
    before = book.levels(perpcarry_cpp.Side.Bid)

    # Enough insertions to force the underlying vector to move, not merely to shift.
    for i in range(5000):
        book.apply(perpcarry_cpp.Side.Bid, 1.0 + i, 1.0)

    assert before == sorted(BIDS, reverse=True), "the earlier result must not have changed"
    assert book.levels(perpcarry_cpp.Side.Bid) != before, "a fresh call must see the new state"


def test_a_book_obtained_from_a_replayer_outlives_the_local_reference():
    """The second lifetime hazard, which the spec did not name.

    ``BookReplayer::book()`` returns a C++ reference. Bound without
    ``reference_internal`` it would let Python drop the replayer while still holding the
    book, and read freed memory -- so this pins the keep-alive relationship, not just the
    values.
    """
    replayer = perpcarry_cpp.BookReplayer()
    replayer.apply_batch(snapshot_batch())
    book = replayer.book()

    del replayer  # the book must keep its owner alive

    assert book.best_bid() == max(BIDS)
    assert book.level_count(perpcarry_cpp.Side.Ask) == len(ASKS)


def test_invalid_updates_raise_rather_than_being_swallowed():
    """M3-T1 test 6 -- a rejected update must not cross as a no-op."""
    book = perpcarry_cpp.OrderBook()

    with pytest.raises(ValueError):
        book.apply(perpcarry_cpp.Side.Bid, float("nan"), 1.0)
    with pytest.raises(ValueError):
        book.apply(perpcarry_cpp.Side.Bid, -1.0, 1.0)
    with pytest.raises(ValueError):
        book.apply(perpcarry_cpp.Side.Bid, 100.0, -1.0)

    assert book.level_count(perpcarry_cpp.Side.Bid) == 0


def test_replay_errors_are_catchable_as_their_own_type():
    """A replay that rejects its input is a different situation from a bug in the caller."""
    replayer = perpcarry_cpp.BookReplayer()

    # The first row must be a snapshot: this feed carries no sequence number and cannot
    # recover from starting mid-stream.
    with pytest.raises(perpcarry_cpp.BookReplayError):
        replayer.apply_batch(
            [
                perpcarry_cpp.BookUpdate(
                    timestamp=1000, side=perpcarry_cpp.Side.Bid, price=100.0, quantity=1.0
                )
            ]
        )


def test_apply_batch_replays_and_stats_cross():
    """M3-T1 test 7."""
    batch = snapshot_batch()
    replayer = perpcarry_cpp.BookReplayer()

    applied = replayer.apply_batch(batch)

    assert applied == len(batch)
    stats = replayer.stats()
    assert stats.applied == len(batch)
    assert stats.snapshot_rows == len(batch)
    assert stats.resyncs == 0
    assert stats.last_timestamp == 1000
    assert replayer.book().best_bid() == max(BIDS)


def test_the_replayer_has_no_single_row_entry_point():
    """Risk R4, as a regression guard.

    The boundary is the batch. A per-row ``apply`` on the replayer is the R4 mistake in its
    most tempting form -- it would look like a convenience and would put the interop cost on
    every event in the feed.
    """
    assert not hasattr(perpcarry_cpp.BookReplayer, "apply")


def test_replaying_the_same_batch_twice_gives_the_identical_state():
    """M3-T1 test 8 -- determinism has to survive the boundary, not merely hold inside it."""
    batch = snapshot_batch()

    first = perpcarry_cpp.BookReplayer()
    first.apply_batch(batch)
    second = perpcarry_cpp.BookReplayer()
    second.apply_batch(batch)

    for side in (perpcarry_cpp.Side.Bid, perpcarry_cpp.Side.Ask):
        assert first.book().levels(side) == second.book().levels(side)
    assert first.stats().applied == second.stats().applied
