// Snapshot + diff replay over an L2 book. See docs/specs/M2/M2-T2-book-replay.md.
//
// This feed carries no sequence number (design doc §3.2, blockers B-003), so a dropped
// diff cannot be detected from the data itself. Correctness rests entirely on comparing
// replayed state against the vendor's independently-constructed book_snapshot_25 -- which
// is why the preconditions below are checked rather than assumed.
#ifndef PERPCARRY_BOOK_REPLAYER_HPP
#define PERPCARRY_BOOK_REPLAYER_HPP

#include <cstddef>
#include <cstdint>
#include <span>
#include <stdexcept>
#include <string>

#include "perpcarry/order_book.hpp"

namespace perpcarry {

// One row of §3.2, as it will cross the pybind11 boundary in M3-T1 (D-012). Timestamps are
// milliseconds; the microsecond capture latency lives in a separate column upstream (D-013)
// and is not needed to replay.
struct BookUpdate {
  std::int64_t timestamp = 0;
  std::int64_t local_timestamp = 0;
  bool is_snapshot = false;
  Side side = Side::Bid;
  double price = 0.0;
  double quantity = 0.0;  // 0 == remove this level
};

class BookReplayError : public std::runtime_error {
 public:
  explicit BookReplayError(const std::string& what) : std::runtime_error(what) {}
};

class BookReplayer {
 public:
  // What a replay contained, so a run is characterised rather than merely completed. A day
  // that finishes without error but logs 400,000 crossed observations has told you
  // something; a void return would not have.
  struct Stats {
    std::int64_t applied = 0;         // rows consumed
    std::int64_t resyncs = 0;         // mid-stream snapshot blocks, excluding the opening one
    std::int64_t snapshot_rows = 0;   // rows with is_snapshot set, including the opening block
    std::int64_t removals = 0;        // quantity == 0 rows
    std::int64_t crossed = 0;         // updates after which best_bid >= best_ask
    std::int64_t last_timestamp = 0;  // ms of the most recent row
  };

  // Applies one row.
  //
  // Throws BookReplayError when the first row is not a snapshot (replay would have no
  // initial state, and this feed cannot recover from that), or when a timestamp goes
  // backwards (the input was reordered somewhere, which otherwise yields a plausible book
  // and no error at all).
  void apply(const BookUpdate& update);

  // Applies a batch in order and returns the number of rows applied. A batch, never a
  // path: the C++ core does no file I/O (D-012), and in M3-T1 this span becomes a
  // zero-copy view over a buffer Python built.
  std::size_t apply_batch(std::span<const BookUpdate> batch);

  const OrderBook& book() const { return book_; }
  const Stats& stats() const { return stats_; }

 private:
  OrderBook book_;
  Stats stats_;
  bool started_ = false;
  // Starts true so the opening snapshot block -- which has no preceding diff -- is not
  // counted as a resync. Deliberately identical to fetch_book.ingest's `prev_snapshot`
  // convention; the two definitions must not drift.
  bool previous_was_snapshot_ = true;
};

}  // namespace perpcarry

#endif  // PERPCARRY_BOOK_REPLAYER_HPP
