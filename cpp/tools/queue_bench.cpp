// perpcarry_queue_bench -- M3-T2's throughput measurement.
//
//   ./build/dev/cpp/tools/perpcarry_queue_bench [ITEMS] [CAPACITY] [OUTPUT_JSON]
//
// Lives in cpp/tools/ rather than cpp/tests/ for two reasons: it writes a file, and the core
// does none (D-012); and a wall-clock measurement has no business being a pass/fail unit
// test, where it would be flaky on a loaded machine and would tell you nothing when it
// failed.
//
// Read the number honestly. In a backtest the producer is reading a file, so this queue is
// not on a latency-critical path in any live sense (D-020). What this measures is the
// structure's capacity in isolation, on one machine, with a trivially copyable element --
// an upper bound on what the boundary could cost, not a claim about the backtest.
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <string>
#include <thread>
#include <vector>

#include "perpcarry/book_replayer.hpp"
#include "perpcarry/spsc_queue.hpp"

namespace {

const char* compiler_id() {
#if defined(__clang__)
  return "clang " __clang_version__;
#elif defined(__GNUC__)
  return "gcc " __VERSION__;
#else
  return "unknown";
#endif
}

const char* architecture() {
#if defined(__aarch64__) || defined(_M_ARM64)
  return "arm64";
#elif defined(__x86_64__) || defined(_M_X64)
  return "x86_64";
#else
  return "unknown";
#endif
}

}  // namespace

namespace {

// One full transfer of `items` through a fresh queue. Returns items/sec, or 0 if the
// transfer was not exact -- a throughput number for a run that lost items would be a
// number for the wrong thing.
double measure_once(std::int64_t items, std::size_t capacity) {
  using Element = perpcarry::BookUpdate;
  perpcarry::SPSCQueue<Element> queue(capacity);
  std::atomic<bool> start{false};

  std::thread producer([&] {
    while (!start.load(std::memory_order_acquire)) {
    }
    for (std::int64_t i = 0; i < items; ++i) {
      Element update;
      update.timestamp = i;
      update.price = 100.0;
      update.quantity = 1.0;
      while (!queue.try_push(update)) std::this_thread::yield();
    }
  });

  const auto begin = std::chrono::steady_clock::now();
  start.store(true, std::memory_order_release);

  std::int64_t popped = 0;
  std::int64_t checksum = 0;
  Element out;
  while (popped < items) {
    if (!queue.try_pop(out)) {
      std::this_thread::yield();
      continue;
    }
    // Consuming the value keeps the optimiser from deleting the loop it is here to time.
    checksum += out.timestamp;
    ++popped;
  }
  const auto end = std::chrono::steady_clock::now();
  producer.join();

  const std::int64_t expected =
      items % 2 == 0 ? (items / 2) * (items - 1) : items * ((items - 1) / 2);
  if (checksum != expected || popped != items) return 0.0;

  const double seconds = std::chrono::duration<double>(end - begin).count();
  return seconds > 0.0 ? static_cast<double>(items) / seconds : 0.0;
}

}  // namespace

int main(int argc, char** argv) {
  const std::int64_t items = argc > 1 ? std::atoll(argv[1]) : 50'000'000;
  const std::size_t capacity = argc > 2 ? std::stoul(argv[2]) : 65536;

  // Repeat and report the spread, because a single sample here is not a measurement:
  // observed 2026-08-29, consecutive uncontrolled runs on an idle machine ranged 35.6M to
  // 46.1M items/sec, a ~25% spread that would let any one run be quoted as the answer.
  constexpr int kRuns = 7;
  std::vector<double> results;
  results.reserve(kRuns);
  for (int i = 0; i < kRuns; ++i) {
    const double result = measure_once(items, capacity);
    if (result == 0.0) {
      std::cerr << "benchmark did not transfer every item; refusing to report a number\n";
      return 1;
    }
    results.push_back(result);
  }
  std::sort(results.begin(), results.end());
  const double median = results[results.size() / 2];
  const double per_second = median;
  const double seconds = static_cast<double>(items) / median;

  std::string json;
  json += "{\n";
  json += "  \"task\": \"M3-T2\",\n";
  json += "  \"what\": \"SPSCQueue<BookUpdate> single-producer/single-consumer throughput\",\n";
  json += "  \"runs\": " + std::to_string(kRuns) + ",\n";
  json += "  \"items\": " + std::to_string(items) + ",\n";
  json += "  \"capacity\": " +
          std::to_string(perpcarry::SPSCQueue<perpcarry::BookUpdate>(capacity).capacity()) +
          ",\n";
  json += "  \"element_bytes\": " + std::to_string(sizeof(perpcarry::BookUpdate)) + ",\n";
  json += "  \"seconds_at_median\": " + std::to_string(seconds) + ",\n";
  json += "  \"items_per_second_median\": " + std::to_string(per_second) + ",\n";
  json += "  \"items_per_second_min\": " + std::to_string(results.front()) + ",\n";
  json += "  \"items_per_second_max\": " + std::to_string(results.back()) + ",\n";
  json += "  \"architecture\": \"" + std::string(architecture()) + "\",\n";
  json += "  \"cache_line_bytes\": " + std::to_string(perpcarry::detail::kCacheLine) + ",\n";
  json += "  \"compiler\": \"" + std::string(compiler_id()) + "\",\n";
  json += "  \"build_type\": \"" + std::string(PERPCARRY_BUILD_TYPE) + "\",\n";
  json += "  \"caveat\": \"One machine, one process, trivially copyable element, consumer "
          "that does no work. An upper bound on the boundary's capacity in isolation -- not "
          "a claim about backtest latency, where the producer is reading a file (D-020). "
          "Quote the median with its range, never the maximum. Note also that repeating "
          "in-process reports higher numbers than separate invocations do (~57M vs ~46M "
          "measured 2026-08-29): these runs are warm, and a cold first event is what the "
          "real pipeline actually sees.\"\n";
  json += "}\n";

  std::cout << json;
  if (argc > 3) {
    std::ofstream out_file(argv[3]);
    if (!out_file) {
      std::cerr << "error: cannot write " << argv[3] << "\n";
      return 2;
    }
    out_file << json;
  }
  return 0;
}
