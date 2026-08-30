#include "perpcarry/pipeline.hpp"

#include <atomic>
#include <exception>
#include <thread>

#include "perpcarry/spsc_queue.hpp"

namespace perpcarry {

Pipeline::Pipeline(std::size_t queue_capacity) : queue_capacity_(queue_capacity) {}

PipelineResult Pipeline::run(std::span<const BookUpdate> batch) {
  PipelineResult result;
  SPSCQueue<BookUpdate> queue(queue_capacity_);
  result.queue_capacity = queue.capacity();

  const std::int64_t total = static_cast<std::int64_t>(batch.size());

  // Set when either side fails, so the other stops instead of waiting on a peer that is
  // never coming back. Without it a consumer that throws leaves the producer spinning
  // against a full queue and run() never returns -- a hang is a worse failure than an
  // exception, because it has no message.
  std::atomic<bool> aborted{false};
  std::exception_ptr producer_error;
  std::exception_ptr consumer_error;
  std::atomic<std::int64_t> producer_stalls{0};

  std::thread producer([&] {
    try {
      for (const BookUpdate& update : batch) {
        while (!queue.try_push(update)) {
          if (aborted.load(std::memory_order_acquire)) return;
          producer_stalls.fetch_add(1, std::memory_order_relaxed);
          std::this_thread::yield();
        }
      }
    } catch (...) {
      producer_error = std::current_exception();
      aborted.store(true, std::memory_order_release);
    }
  });

  BookUpdate update;
  try {
    while (result.consumed < total) {
      if (!queue.try_pop(update)) {
        if (aborted.load(std::memory_order_acquire)) break;
        ++result.consumer_stalls;
        std::this_thread::yield();
        continue;
      }
      // Sampled after the pop, so it reports what the queue held while work was flowing
      // rather than the zero it settles at once the producer is done.
      const std::size_t occupancy = queue.size_approx();
      if (occupancy > result.peak_queue_occupancy) result.peak_queue_occupancy = occupancy;

      replayer_.apply(update);
      ++result.consumed;
    }
  } catch (...) {
    consumer_error = std::current_exception();
    // Told before the join, or the producer waits on a queue nothing will drain again.
    aborted.store(true, std::memory_order_release);
  }

  producer.join();
  result.producer_stalls = producer_stalls.load(std::memory_order_relaxed);
  result.replay = replayer_.stats();

  // Consumer first: it is the side that runs the replay, so its error is the one that
  // explains a malformed stream. A producer error at this point could only be an allocation
  // failure, which is not the interesting story.
  if (consumer_error) std::rethrow_exception(consumer_error);
  if (producer_error) std::rethrow_exception(producer_error);
  return result;
}

}  // namespace perpcarry
