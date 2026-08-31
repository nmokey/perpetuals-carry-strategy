// perpcarry_impact_probe -- M4's real-data validation harness.
//
//   uv run python -m perpcarry.tools.export_book --symbol 0GUSDT --date 2026-06-01
//   ./build/dev/cpp/tools/perpcarry_impact_probe <dir>/events.csv [SUMMARY_JSON]
//
// Why this exists. M4-T1's depth finding and M4-T2's sliced behaviour were first measured with a
// throwaway program, and the numbers went into the specs, progress log and CLAUDE.md with nothing
// able to regenerate them. Every other milestone here ships a committed artifact that says
// "re-run to reproduce"; a published number that cannot be reproduced is a claim about one
// afternoon.
//
// Its input is licensed vendor book data: never commit it, never let it reach CI. The aggregate
// JSON is the only publishable output -- rates and means over a whole day expose no rows and
// cannot reconstruct a book (Tardis Clause 9.2(2)).
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <exception>
#include <fstream>
#include <iostream>
#include <span>
#include <string>
#include <vector>

#include "event_csv.hpp"
#include "perpcarry/book_replayer.hpp"
#include "perpcarry/impact_simulator.hpp"

namespace {

using perpcarry::BookReplayer;
using perpcarry::BookUpdate;
using perpcarry::Fill;
using perpcarry::OrderSide;
using perpcarry::SlicedFill;
using perpcarry::SliceSchedule;

// Sizes in base units, spanning the range a capacity study sweeps. Reported alongside the fraction
// of ADV they represent only in the write-up: this tool has no symbol identity and deliberately
// reads no corpus metadata, so it emits base units and lets M4-T3 do the normalisation.
constexpr double kSizes[] = {100.0, 1000.0, 10000.0, 50000.0, 200000.0, 1000000.0};

// One instant in every N events. The book barely changes between adjacent events, so sampling
// costs almost nothing in fidelity and keeps the sweep O(day / N).
constexpr std::int64_t kSampleEvery = 5000;

struct SizeStats {
  double size = 0.0;
  std::int64_t samples = 0;
  std::int64_t beyond_validated_depth = 0;
  std::int64_t exhausted = 0;
  std::int64_t crossed = 0;
  double slippage_sum = 0.0;
  std::int64_t slippage_samples = 0;

  // M4-T2, on the same instants: the same parent size worked over a window rather than taken at
  // once. This is the only place the sliced simulator meets real data.
  double sliced_slippage_sum = 0.0;
  std::int64_t sliced_samples = 0;
  std::int64_t sliced_cheaper = 0;
};

void accumulate(SizeStats& stats, const Fill& fill) {
  ++stats.samples;
  if (fill.beyond_validated_depth) ++stats.beyond_validated_depth;
  if (fill.exhausted_book) ++stats.exhausted;
  if (fill.crossed_at_entry) ++stats.crossed;
  if (fill.filled_quantity > 0.0 && std::isfinite(fill.slippage_vs_mid_bps)) {
    stats.slippage_sum += fill.slippage_vs_mid_bps;
    ++stats.slippage_samples;
  }
}

double rate(std::int64_t numerator, std::int64_t denominator) {
  return denominator > 0 ? static_cast<double>(numerator) / static_cast<double>(denominator) : 0.0;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 2 || argc > 3) {
    std::cerr << "usage: " << argv[0] << " EVENTS_CSV [SUMMARY_JSON]\n";
    return 2;
  }

  try {
    std::ifstream events(argv[1]);
    if (!events) {
      std::cerr << "error: cannot open events csv: " << argv[1] << "\n";
      return 2;
    }

    perpcarry::tools::EventStream stream(events);
    BookReplayer replayer;
    std::vector<SizeStats> stats;
    for (const double size : kSizes) stats.push_back(SizeStats{size, 0, 0, 0, 0, 0.0, 0, 0.0, 0, 0});

    // The sliced comparison needs future events, so it replays its own window from a buffer rather
    // than borrowing the streaming replayer -- which must never look ahead.
    std::vector<BookUpdate> window;
    constexpr std::int64_t kWindowMs = 10'000;   // 10 s
    constexpr std::size_t kSlices = 5;

    std::int64_t rows = 0;
    std::int64_t sampled = 0;
    std::int64_t first_timestamp = 0;
    std::int64_t last_timestamp = 0;

    while (stream.has()) {
      const BookUpdate update = stream.peek();
      replayer.apply(update);
      stream.advance();
      if (rows == 0) first_timestamp = update.timestamp;
      last_timestamp = update.timestamp;
      ++rows;

      // Keep a trailing buffer so a slice schedule starting here has events to replay forward
      // through. Bounded, so a full day never materialises.
      window.push_back(update);
      if (window.size() > 200000) {
        window.erase(window.begin(), window.begin() + 100000);
      }

      if (rows % kSampleEvery != 0) continue;
      ++sampled;

      for (SizeStats& s : stats) {
        accumulate(s, perpcarry::simulate_market_order(replayer.book(), OrderSide::Buy, s.size));
      }
    }

    // A second pass for the sliced comparison, over a bounded sample of windows. Separate because
    // it needs each window's *future*, which the single streaming pass by construction does not
    // have.
    std::ifstream again(argv[1]);
    perpcarry::tools::EventStream replay(again);
    std::vector<BookUpdate> all;
    while (replay.has()) {
      all.push_back(replay.peek());
      replay.advance();
    }

    constexpr std::size_t kSlicedSamples = 40;
    const std::size_t stride = all.size() > kSlicedSamples ? all.size() / kSlicedSamples : 1;
    for (std::size_t start = 0; start + 1 < all.size(); start += stride) {
      const std::int64_t t0 = all[start].timestamp;
      // Everything from the beginning through the end of the window: the replayer needs the
      // opening snapshot, so the span always starts at row 0.
      std::size_t end = start;
      while (end < all.size() && all[end].timestamp <= t0 + kWindowMs) ++end;
      if (end >= all.size()) break;

      const std::span<const BookUpdate> span(all.data(), end);
      for (SizeStats& s : stats) {
        SliceSchedule schedule;
        schedule.start_timestamp = t0;
        schedule.duration_ms = kWindowMs;
        schedule.slices = kSlices;

        SliceSchedule immediate = schedule;
        immediate.duration_ms = 0;
        immediate.slices = 1;

        const SlicedFill worked =
            perpcarry::simulate_sliced_execution(span, OrderSide::Buy, s.size, schedule);
        const SlicedFill at_once =
            perpcarry::simulate_sliced_execution(span, OrderSide::Buy, s.size, immediate);

        if (!std::isfinite(worked.parent.slippage_vs_mid_bps) ||
            !std::isfinite(at_once.parent.slippage_vs_mid_bps)) {
          continue;
        }
        s.sliced_slippage_sum += worked.parent.slippage_vs_mid_bps;
        ++s.sliced_samples;
        if (worked.parent.slippage_vs_mid_bps < at_once.parent.slippage_vs_mid_bps) {
          ++s.sliced_cheaper;
        }
      }
    }

    std::string json;
    json += "{\n";
    json += "  \"task\": \"M4\",\n";
    json += "  \"what\": \"impact simulator sweep over a replayed symbol-day\",\n";
    json += "  \"produced_by\": \"perpcarry_impact_probe; re-run to reproduce\",\n";
    json += "  \"events\": " + std::to_string(rows) + ",\n";
    json += "  \"sampled_instants\": " + std::to_string(sampled) + ",\n";
    json += "  \"sample_every_n_events\": " + std::to_string(kSampleEvery) + ",\n";
    json += "  \"first_timestamp\": " + std::to_string(first_timestamp) + ",\n";
    json += "  \"last_timestamp\": " + std::to_string(last_timestamp) + ",\n";
    json += "  \"validated_depth\": " + std::to_string(perpcarry::kValidatedDepth) + ",\n";
    json += "  \"sliced_window_ms\": " + std::to_string(kWindowMs) + ",\n";
    json += "  \"sliced_slices\": " + std::to_string(kSlices) + ",\n";
    json += "  \"sizes\": [\n";
    for (std::size_t i = 0; i < stats.size(); ++i) {
      const SizeStats& s = stats[i];
      json += "    {";
      json += "\"size\": " + std::to_string(static_cast<std::int64_t>(s.size)) + ", ";
      json += "\"beyond_validated_depth_rate\": " +
              std::to_string(rate(s.beyond_validated_depth, s.samples)) + ", ";
      json += "\"exhausted_rate\": " + std::to_string(rate(s.exhausted, s.samples)) + ", ";
      json += "\"crossed_rate\": " + std::to_string(rate(s.crossed, s.samples)) + ", ";
      json += "\"mean_slippage_bps\": " +
              std::to_string(s.slippage_samples ? s.slippage_sum / s.slippage_samples : 0.0) + ", ";
      json += "\"sliced_mean_slippage_bps\": " +
              std::to_string(s.sliced_samples ? s.sliced_slippage_sum / s.sliced_samples : 0.0) +
              ", ";
      json += "\"sliced_cheaper_rate\": " +
              std::to_string(rate(s.sliced_cheaper, s.sliced_samples)) + ", ";
      json += "\"sliced_samples\": " + std::to_string(s.sliced_samples);
      json += "}";
      if (i + 1 < stats.size()) json += ",";
      json += "\n";
    }
    json += "  ]\n";
    json += "}\n";

    std::cout << json;
    if (argc == 3) {
      std::ofstream out(argv[2]);
      if (!out) {
        std::cerr << "error: cannot write " << argv[2] << "\n";
        return 2;
      }
      out << json;
    }
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "error: " << error.what() << "\n";
    return 1;
  }
}
