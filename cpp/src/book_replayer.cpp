#include "perpcarry/book_replayer.hpp"

#include <string>

namespace perpcarry {

void BookReplayer::apply(const BookUpdate& update) {
  if (!started_ && !update.is_snapshot) {
    throw BookReplayError(
        "replay does not open with an is_snapshot block: there is no initial state to build "
        "on, and this feed carries no sequence number to recover from (design doc 3.2)");
  }

  // Equal timestamps are ordinary -- a median of 3.83 rows share a millisecond around a
  // reference image on 0GUSDT 2026-06-01, so ties are the common case and file order is
  // what sequences them. A *decrease* means the input was reordered upstream.
  if (started_ && update.timestamp < stats_.last_timestamp) {
    throw BookReplayError("book updates went backwards in time: " +
                          std::to_string(update.timestamp) + " follows " +
                          std::to_string(stats_.last_timestamp) +
                          "; file order is the sequence and must be preserved");
  }

  // A snapshot row following a diff is the vendor resyncing mid-day: the block is a fresh
  // book image, so state must be reset before it is applied rather than the rows being
  // applied as diffs onto a stale book. Measured: 13 such events on both 0GUSDT and
  // BTCUSDT for 2026-06-01.
  if (update.is_snapshot && !previous_was_snapshot_) {
    book_.clear();
    ++stats_.resyncs;
  }

  book_.apply(update.side, update.price, update.quantity);

  ++stats_.applied;
  if (update.is_snapshot) {
    ++stats_.snapshot_rows;
  }
  if (update.quantity == 0.0) {
    ++stats_.removals;
  }
  if (book_.is_crossed()) {
    ++stats_.crossed;
  }
  stats_.last_timestamp = update.timestamp;
  previous_was_snapshot_ = update.is_snapshot;
  started_ = true;
}

std::size_t BookReplayer::apply_batch(std::span<const BookUpdate> batch) {
  for (const BookUpdate& update : batch) {
    apply(update);
  }
  return batch.size();
}

}  // namespace perpcarry
