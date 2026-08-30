// M2-T2 -- snapshot + diff replay logic.
// Spec: docs/specs/M2/M2-T2-book-replay.md
//
// Every fixture here is synthetic. The vendor's terms forbid book rows entering the repo
// or CI (Tardis Clause 9.2(2), convention C9), so the real-data comparison is a local run
// (D-018) and this file covers the mechanism instead.

#include <catch2/catch_test_macros.hpp>

#include <cstddef>
#include <cstdint>
#include <span>
#include <vector>

#include "perpcarry/book_compare.hpp"
#include "perpcarry/book_replayer.hpp"
#include "perpcarry/order_book.hpp"

using perpcarry::BookDiff;
using perpcarry::BookReplayer;
using perpcarry::BookReplayError;
using perpcarry::BookUpdate;
using perpcarry::compare_top_n;
using perpcarry::DiffKind;
using perpcarry::Level;
using perpcarry::OrderBook;
using perpcarry::Side;

namespace {

BookUpdate snap(std::int64_t ts, Side side, double price, double quantity) {
  return BookUpdate{ts, ts + 2, true, side, price, quantity};
}

BookUpdate diff(std::int64_t ts, Side side, double price, double quantity) {
  return BookUpdate{ts, ts + 2, false, side, price, quantity};
}

// A minimal well-formed day: an opening snapshot block, then diffs.
std::vector<BookUpdate> opening_block(std::int64_t ts = 1000) {
  return {
      snap(ts, Side::Bid, 100.0, 5.0),
      snap(ts, Side::Bid, 99.0, 6.0),
      snap(ts, Side::Ask, 101.0, 7.0),
      snap(ts, Side::Ask, 102.0, 8.0),
  };
}

std::vector<Level> levels_of(const OrderBook& book, Side side) {
  const std::span<const Level> view = book.levels(side);
  return std::vector<Level>(view.begin(), view.end());
}

}  // namespace

TEST_CASE("an opening snapshot block builds the initial state", "[replayer]") {
  BookReplayer replayer;
  REQUIRE(replayer.book().level_count(Side::Bid) == 0);
  REQUIRE(replayer.book().level_count(Side::Ask) == 0);

  const std::vector<BookUpdate> block = opening_block();
  REQUIRE(replayer.apply_batch(block) == block.size());

  REQUIRE(replayer.book().best_bid()->price == 100.0);
  REQUIRE(replayer.book().best_ask()->price == 101.0);
  REQUIRE(replayer.stats().applied == 4);
  REQUIRE(replayer.stats().snapshot_rows == 4);
  REQUIRE(replayer.stats().resyncs == 0);  // the opening block is not a resync
}

TEST_CASE("a replay that does not open with a snapshot is rejected", "[replayer]") {
  BookReplayer replayer;
  const std::vector<BookUpdate> rows = {diff(1000, Side::Bid, 100.0, 5.0)};

  REQUIRE_THROWS_AS(replayer.apply_batch(rows), BookReplayError);
  REQUIRE(replayer.stats().applied == 0);
}

TEST_CASE("diffs after the opening block apply as diffs, not as a reset", "[replayer]") {
  BookReplayer replayer;
  replayer.apply_batch(opening_block());

  const std::vector<BookUpdate> diffs = {
      diff(1001, Side::Bid, 100.5, 1.0),  // new best bid
      diff(1002, Side::Bid, 99.0, 0.0),   // remove a level
  };
  replayer.apply_batch(diffs);

  REQUIRE(replayer.book().best_bid()->price == 100.5);
  REQUIRE(replayer.book().level_count(Side::Bid) == 2);  // 100.5 and 100.0 survive
  REQUIRE(replayer.book().level_count(Side::Ask) == 2);  // untouched by the diffs
  REQUIRE(replayer.stats().resyncs == 0);
  REQUIRE(replayer.stats().removals == 1);
}

TEST_CASE("a snapshot block after a diff resets the book", "[replayer]") {
  BookReplayer replayer;
  replayer.apply_batch(opening_block());
  replayer.apply_batch(std::vector<BookUpdate>{diff(1001, Side::Bid, 100.5, 1.0)});

  // The vendor resyncing mid-day: a fresh image, which must replace state rather than be
  // applied on top of it.
  const std::vector<BookUpdate> resync = {
      snap(2000, Side::Bid, 50.0, 1.0),
      snap(2000, Side::Ask, 51.0, 1.0),
  };
  replayer.apply_batch(resync);

  REQUIRE(replayer.stats().resyncs == 1);
  REQUIRE(replayer.book().level_count(Side::Bid) == 1);
  REQUIRE(replayer.book().level_count(Side::Ask) == 1);
  REQUIRE(replayer.book().best_bid()->price == 50.0);
  REQUIRE(replayer.book().best_ask()->price == 51.0);
}

TEST_CASE("consecutive snapshot rows are one block, not one reset each", "[replayer]") {
  BookReplayer replayer;
  replayer.apply_batch(opening_block());
  replayer.apply_batch(std::vector<BookUpdate>{diff(1001, Side::Bid, 100.5, 1.0)});

  const std::vector<BookUpdate> resync = {
      snap(2000, Side::Bid, 50.0, 1.0),
      snap(2000, Side::Bid, 49.0, 2.0),
      snap(2000, Side::Bid, 48.0, 3.0),
      snap(2000, Side::Ask, 51.0, 4.0),
  };
  replayer.apply_batch(resync);

  // One event, and every row of the block survives -- a per-row reset would leave one.
  REQUIRE(replayer.stats().resyncs == 1);
  REQUIRE(replayer.book().level_count(Side::Bid) == 3);
  REQUIRE(replayer.book().level_count(Side::Ask) == 1);
}

TEST_CASE("a resync split across two batches still resets once", "[replayer]") {
  // Batching is an artifact of the pybind11 boundary (D-012). A replayer whose answer
  // depends on where the caller happened to cut the input is wrong in a way no
  // single-batch test can see.
  BookReplayer split;
  split.apply_batch(opening_block());
  split.apply_batch(std::vector<BookUpdate>{diff(1001, Side::Bid, 100.5, 1.0)});
  split.apply_batch(std::vector<BookUpdate>{snap(2000, Side::Bid, 50.0, 1.0)});
  split.apply_batch(std::vector<BookUpdate>{snap(2000, Side::Bid, 49.0, 2.0)});

  REQUIRE(split.stats().resyncs == 1);
  REQUIRE(split.book().level_count(Side::Bid) == 2);
}

TEST_CASE("a zero-quantity row inside a snapshot block is a no-op", "[replayer]") {
  // BTCUSDT 2026-06-01's opening snapshot block really does carry 13 of these.
  BookReplayer replayer;
  const std::vector<BookUpdate> block = {
      snap(1000, Side::Bid, 100.0, 5.0),
      snap(1000, Side::Bid, 99.0, 0.0),  // removal of a level that was never added
      snap(1000, Side::Ask, 101.0, 7.0),
  };

  REQUIRE_NOTHROW(replayer.apply_batch(block));
  REQUIRE(replayer.book().level_count(Side::Bid) == 1);
  REQUIRE(replayer.stats().removals == 1);
  REQUIRE(replayer.stats().applied == 3);
}

TEST_CASE("a batch whose timestamps go backwards is rejected", "[replayer]") {
  BookReplayer replayer;
  replayer.apply_batch(opening_block(1000));

  const std::vector<BookUpdate> backwards = {
      diff(1005, Side::Bid, 100.5, 1.0),
      diff(1004, Side::Bid, 100.6, 1.0),
  };
  REQUIRE_THROWS_AS(replayer.apply_batch(backwards), BookReplayError);

  SECTION("equal timestamps are fine -- ties are the common case") {
    BookReplayer ties;
    ties.apply_batch(opening_block(1000));
    const std::vector<BookUpdate> same_ms = {
        diff(1005, Side::Bid, 100.5, 1.0),
        diff(1005, Side::Bid, 100.6, 1.0),
        diff(1005, Side::Ask, 100.9, 1.0),
    };
    REQUIRE_NOTHROW(ties.apply_batch(same_ms));
    REQUIRE(ties.stats().applied == 7);
  }
}

TEST_CASE("a batch starting before the previous batch ended is rejected", "[replayer]") {
  BookReplayer replayer;
  replayer.apply_batch(opening_block(1000));
  replayer.apply_batch(std::vector<BookUpdate>{diff(2000, Side::Bid, 100.5, 1.0)});

  const std::vector<BookUpdate> stale = {diff(1999, Side::Bid, 100.6, 1.0)};
  REQUIRE_THROWS_AS(replayer.apply_batch(stale), BookReplayError);
}

TEST_CASE("stats characterise the replay", "[replayer]") {
  BookReplayer replayer;
  replayer.apply_batch(opening_block(1000));                                   // 4 snapshot rows
  replayer.apply_batch(std::vector<BookUpdate>{diff(1001, Side::Bid, 99.0, 0.0),    // removal
                                              diff(1002, Side::Bid, 101.5, 1.0)});  // crosses
  replayer.apply_batch(std::vector<BookUpdate>{snap(2000, Side::Bid, 50.0, 1.0),
                                               snap(2000, Side::Ask, 51.0, 1.0)});  // resync

  const BookReplayer::Stats& stats = replayer.stats();
  REQUIRE(stats.applied == 8);
  REQUIRE(stats.snapshot_rows == 6);
  REQUIRE(stats.resyncs == 1);
  REQUIRE(stats.removals == 1);
  REQUIRE(stats.crossed == 1);  // only after 101.5 crossed the 101.0 ask
  REQUIRE(stats.last_timestamp == 2000);
  REQUIRE_FALSE(replayer.book().is_crossed());  // the resync cleared it
}

TEST_CASE("replay is invariant to how the input is batched", "[replayer]") {
  std::vector<BookUpdate> rows = opening_block(1000);
  rows.push_back(diff(1001, Side::Bid, 100.5, 3.0));
  rows.push_back(diff(1002, Side::Ask, 101.0, 0.0));
  rows.push_back(snap(2000, Side::Bid, 50.0, 1.0));
  rows.push_back(snap(2000, Side::Ask, 51.0, 2.0));
  rows.push_back(diff(2001, Side::Bid, 50.5, 4.0));

  BookReplayer whole;
  whole.apply_batch(rows);

  BookReplayer row_by_row;
  for (const BookUpdate& row : rows) {
    row_by_row.apply_batch(std::span<const BookUpdate>(&row, 1));
  }

  BookReplayer in_threes;
  for (std::size_t i = 0; i < rows.size(); i += 3) {
    const std::size_t count = std::min<std::size_t>(3, rows.size() - i);
    in_threes.apply_batch(std::span<const BookUpdate>(rows.data() + i, count));
  }

  for (const Side side : {Side::Bid, Side::Ask}) {
    const std::vector<Level> expected = levels_of(whole.book(), side);
    REQUIRE(levels_of(row_by_row.book(), side).size() == expected.size());
    REQUIRE(levels_of(in_threes.book(), side).size() == expected.size());
    for (std::size_t i = 0; i < expected.size(); ++i) {
      REQUIRE(levels_of(row_by_row.book(), side)[i].price == expected[i].price);
      REQUIRE(levels_of(row_by_row.book(), side)[i].quantity == expected[i].quantity);
      REQUIRE(levels_of(in_threes.book(), side)[i].price == expected[i].price);
      REQUIRE(levels_of(in_threes.book(), side)[i].quantity == expected[i].quantity);
    }
  }

  REQUIRE(row_by_row.stats().applied == whole.stats().applied);
  REQUIRE(row_by_row.stats().resyncs == whole.stats().resyncs);
  REQUIRE(row_by_row.stats().removals == whole.stats().removals);
  REQUIRE(row_by_row.stats().crossed == whole.stats().crossed);
  REQUIRE(in_threes.stats().resyncs == whole.stats().resyncs);
  REQUIRE(in_threes.stats().crossed == whole.stats().crossed);
}

TEST_CASE("identical books compare clean", "[compare]") {
  OrderBook book;
  book.apply(Side::Bid, 100.0, 5.0);
  book.apply(Side::Bid, 99.0, 6.0);
  book.apply(Side::Ask, 101.0, 7.0);

  const std::vector<Level> bids = {{100.0, 5.0}, {99.0, 6.0}};
  const std::vector<Level> asks = {{101.0, 7.0}};

  const BookDiff result = compare_top_n(book, bids, asks, 25);
  REQUIRE(result.empty());
}

TEST_CASE("each mismatch category is produced by the defect that should produce it",
          "[compare]") {
  const std::vector<Level> bids = {{100.0, 5.0}, {99.0, 6.0}};
  const std::vector<Level> asks = {{101.0, 7.0}};

  SECTION("a wrong size at a correct price is a quantity mismatch") {
    OrderBook book;
    book.apply(Side::Bid, 100.0, 5.0);
    book.apply(Side::Bid, 99.0, 6.5);  // wrong
    book.apply(Side::Ask, 101.0, 7.0);

    const BookDiff result = compare_top_n(book, bids, asks, 25);
    REQUIRE(result.size() == 1);
    REQUIRE(result.differences[0].kind == DiffKind::QuantityMismatch);
    REQUIRE(result.differences[0].side == Side::Bid);
    REQUIRE(result.differences[0].rank == 1);
    REQUIRE(result.differences[0].replayed.quantity == 6.5);
    REQUIRE(result.differences[0].reference.quantity == 6.0);
  }

  SECTION("a level at the wrong price is a price mismatch") {
    OrderBook book;
    book.apply(Side::Bid, 100.0, 5.0);
    book.apply(Side::Bid, 98.0, 6.0);  // should be 99.0
    book.apply(Side::Ask, 101.0, 7.0);

    const BookDiff result = compare_top_n(book, bids, asks, 25);
    REQUIRE(result.size() == 1);
    REQUIRE(result.differences[0].kind == DiffKind::PriceMismatch);
    REQUIRE(result.differences[0].replayed.price == 98.0);
    REQUIRE(result.differences[0].reference.price == 99.0);
  }

  SECTION("a dropped level is a missing level") {
    OrderBook book;
    book.apply(Side::Bid, 100.0, 5.0);  // 99.0 never arrived
    book.apply(Side::Ask, 101.0, 7.0);

    const BookDiff result = compare_top_n(book, bids, asks, 25);
    REQUIRE(result.size() == 1);
    REQUIRE(result.differences[0].kind == DiffKind::MissingLevel);
    REQUIRE(result.differences[0].rank == 1);
    REQUIRE(result.differences[0].reference.price == 99.0);
  }

  SECTION("a phantom level the reference says does not exist is an extra level") {
    // The reference drops trailing levels only when the book really was thinner (D-014),
    // so a level beyond its end is a level we invented -- exactly what a removal treated
    // as a no-op would leave behind.
    OrderBook book;
    book.apply(Side::Bid, 100.0, 5.0);
    book.apply(Side::Bid, 99.0, 6.0);
    book.apply(Side::Bid, 98.0, 1.0);  // phantom
    book.apply(Side::Ask, 101.0, 7.0);

    const BookDiff result = compare_top_n(book, bids, asks, 25);
    REQUIRE(result.size() == 1);
    REQUIRE(result.differences[0].kind == DiffKind::ExtraLevel);
    REQUIRE(result.differences[0].rank == 2);
    REQUIRE(result.differences[0].replayed.price == 98.0);
  }
}

TEST_CASE("comparison is bounded by depth, not by how deep the replayed book is",
          "[compare]") {
  // The real case: a ~1000-level book against a 25-level image. Levels past the image's
  // depth are the expected shape, not phantoms.
  OrderBook book;
  std::vector<Level> bids;
  for (int i = 0; i < 100; ++i) {
    const double price = 100.0 - static_cast<double>(i) * 0.1;
    book.apply(Side::Bid, price, 1.0 + static_cast<double>(i));
    if (i < 25) {
      bids.push_back(Level{price, 1.0 + static_cast<double>(i)});
    }
  }
  book.apply(Side::Ask, 101.0, 7.0);
  const std::vector<Level> asks = {{101.0, 7.0}};

  REQUIRE(compare_top_n(book, bids, asks, 25).empty());

  SECTION("a defect inside the window is still caught") {
    book.apply(Side::Bid, 100.0, 99.0);
    const BookDiff result = compare_top_n(book, bids, asks, 25);
    REQUIRE(result.size() == 1);
    REQUIRE(result.differences[0].kind == DiffKind::QuantityMismatch);
    REQUIRE(result.differences[0].rank == 0);
  }

  SECTION("a defect outside the window is not, and that is the documented limit") {
    book.apply(Side::Bid, 90.0, 99.0);  // rank 100, far past the reference's 25
    REQUIRE(compare_top_n(book, bids, asks, 25).empty());
  }
}
