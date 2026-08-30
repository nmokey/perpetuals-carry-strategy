// The assembled replay pipeline: ingest thread -> SPSC queue -> replay thread.
// See docs/specs/M3/M3-T3-pipeline-smoke-test.md and OD-6 / D-020.
//
// **This is the only threaded thing in perpcarry_core, and the book is still not.** The
// OrderBook is owned entirely by the consumer thread and touched by nothing else; the
// producer never sees it. "Do not add concurrency to the book core" is intact -- the
// concurrency is *around* the book, at the boundary OD-6 chose to model, which is the
// feed-handler -> strategy-engine split that exists in real systems.
//
// It does no file I/O, so it belongs here rather than in tools/ (D-012): Python reads the
// Parquet and hands over an in-memory batch, and this takes rows, never a path.
//
// The queue sits between replay and simulation on the *C++* side. It is not the
// Python/C++ boundary -- that one is `run()` itself, crossed once per batch, never per
// event (Risk R4).
#ifndef PERPCARRY_PIPELINE_HPP
#define PERPCARRY_PIPELINE_HPP

#include <cstddef>
#include <cstdint>
#include <span>

#include "perpcarry/book_replayer.hpp"
#include "perpcarry/order_book.hpp"

namespace perpcarry {

struct PipelineResult {
  BookReplayer::Stats replay;
  std::int64_t consumed = 0;

  std::size_t queue_capacity = 0;

  // How full the queue actually got. Reported because a pipeline whose consumer kept up so
  // easily that the queue was never occupied has not exercised the thing it exists to
  // test -- everything passes and the concurrency was decorative (C15).
  std::size_t peak_queue_occupancy = 0;

  // Times a push found the queue full / a pop found it empty. Diagnostic only: a decision
  // that depended on either would make the run's output depend on thread timing, which is
  // exactly what D-020 forbids.
  std::int64_t producer_stalls = 0;
  std::int64_t consumer_stalls = 0;
};

class Pipeline {
 public:
  static constexpr std::size_t kDefaultQueueCapacity = 65536;

  explicit Pipeline(std::size_t queue_capacity = kDefaultQueueCapacity);

  // Replays `batch` across two threads and returns when both have joined.
  //
  // Rethrows on the calling thread anything either thread threw -- a BookReplayError from
  // a malformed stream, most likely. Neither thread can be left running and no failure is
  // swallowed: if the consumer dies, the producer is told to stop rather than blocking
  // forever against a queue nobody is draining.
  //
  // Determinism (D-020): the queue changes when an update is applied, never which one or
  // in what order, and nothing here reads the occupancy to make a decision. Replaying the
  // same batch twice therefore gives the same book, which `Pipeline` is tested on directly
  // against a single-threaded replay of the same input.
  PipelineResult run(std::span<const BookUpdate> batch);

  // Valid after run() returns; both threads have joined by then, so this is an ordinary
  // single-threaded read.
  const OrderBook& book() const { return replayer_.book(); }
  const BookReplayer::Stats& stats() const { return replayer_.stats(); }

 private:
  std::size_t queue_capacity_;
  BookReplayer replayer_;
};

}  // namespace perpcarry

#endif  // PERPCARRY_PIPELINE_HPP
