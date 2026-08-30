#include "replay_validate.hpp"

#include <charconv>
#include <fstream>
#include <istream>
#include <ostream>
#include <string>
#include <string_view>
#include <vector>

#include "perpcarry/book_debug.hpp"

namespace perpcarry::tools {
namespace {

// Must match perpcarry.tools.export_book.EVENT_COLUMNS / REFERENCE_COLUMNS. The header is
// checked rather than skipped: a column reordered upstream would otherwise be read as a
// different field and produce a wrong book with no error anywhere (C14).
const std::vector<std::string> kEventColumns = {"timestamp", "local_timestamp", "is_snapshot",
                                                "side",      "price",           "quantity"};
const std::vector<std::string> kReferenceColumns = {"timestamp", "side", "level", "price",
                                                    "quantity"};

std::string_view unquote(std::string_view field) {
  if (field.size() >= 2 && field.front() == '"' && field.back() == '"') {
    return field.substr(1, field.size() - 2);
  }
  return field;
}

void split(std::string_view line, std::vector<std::string_view>& out) {
  out.clear();
  std::size_t start = 0;
  while (true) {
    const std::size_t comma = line.find(',', start);
    if (comma == std::string_view::npos) {
      out.push_back(unquote(line.substr(start)));
      return;
    }
    out.push_back(unquote(line.substr(start, comma - start)));
    start = comma + 1;
  }
}

std::int64_t parse_int(std::string_view field, const char* what) {
  std::int64_t value = 0;
  const auto result = std::from_chars(field.data(), field.data() + field.size(), value);
  if (result.ec != std::errc() || result.ptr != field.data() + field.size()) {
    throw ValidationError(std::string("could not parse ") + what + " as an integer: '" +
                          std::string(field) + "'");
  }
  return value;
}

double parse_double(std::string_view field, const char* what) {
  // std::from_chars, not strtod: it is locale-independent by construction, and a decimal
  // separator that follows the environment is exactly the kind of thing that silently
  // truncates every price on someone else's machine.
  double value = 0.0;
  const auto result = std::from_chars(field.data(), field.data() + field.size(), value);
  if (result.ec != std::errc() || result.ptr != field.data() + field.size()) {
    throw ValidationError(std::string("could not parse ") + what + " as a number: '" +
                          std::string(field) + "'");
  }
  return value;
}

Side parse_side(std::string_view field) {
  if (field == "bid") return Side::Bid;
  if (field == "ask") return Side::Ask;
  throw ValidationError("unknown side '" + std::string(field) + "', expected bid or ask");
}

bool parse_bool(std::string_view field) {
  if (field == "true" || field == "1") return true;
  if (field == "false" || field == "0") return false;
  throw ValidationError("unknown boolean '" + std::string(field) + "'");
}

class CsvReader {
 public:
  CsvReader(std::istream& in, const std::vector<std::string>& expected, const char* what)
      : in_(in) {
    if (!std::getline(in_, line_)) {
      throw ValidationError(std::string(what) + " csv is empty: expected a header row");
    }
    if (!line_.empty() && line_.back() == '\r') line_.pop_back();
    split(line_, fields_);
    if (fields_.size() != expected.size()) {
      throw ValidationError(std::string(what) + " csv has " + std::to_string(fields_.size()) +
                            " columns, expected " + std::to_string(expected.size()));
    }
    for (std::size_t i = 0; i < expected.size(); ++i) {
      if (fields_[i] != expected[i]) {
        throw ValidationError(std::string(what) + " csv column " + std::to_string(i) + " is '" +
                              std::string(fields_[i]) + "', expected '" + expected[i] + "'");
      }
    }
  }

  // Fields remain valid until the next call.
  const std::vector<std::string_view>* next() {
    if (!std::getline(in_, line_)) return nullptr;
    if (!line_.empty() && line_.back() == '\r') line_.pop_back();
    if (line_.empty()) return next();
    split(line_, fields_);
    return &fields_;
  }

 private:
  std::istream& in_;
  std::string line_;
  std::vector<std::string_view> fields_;
};

// One-row lookahead over the event stream, so the group of events sharing a millisecond
// can be counted only once its end is known.
class EventStream {
 public:
  explicit EventStream(std::istream& in) : csv_(in, kEventColumns, "events") { advance(); }

  bool has() const { return has_; }
  const BookUpdate& peek() const { return pending_; }

  void advance() {
    const std::vector<std::string_view>* fields = csv_.next();
    if (fields == nullptr) {
      has_ = false;
      return;
    }
    pending_.timestamp = parse_int((*fields)[0], "event timestamp");
    pending_.local_timestamp = parse_int((*fields)[1], "event local_timestamp");
    pending_.is_snapshot = parse_bool((*fields)[2]);
    pending_.side = parse_side((*fields)[3]);
    pending_.price = parse_double((*fields)[4], "event price");
    pending_.quantity = parse_double((*fields)[5], "event quantity");
    has_ = true;
  }

 private:
  CsvReader csv_;
  BookUpdate pending_;
  bool has_ = false;
};

struct ReferenceImage {
  std::int64_t timestamp = 0;
  std::vector<Level> bids;
  std::vector<Level> asks;
  std::int64_t rows = 0;
};

// Accumulates rows sharing a timestamp into one image.
class ReferenceStream {
 public:
  explicit ReferenceStream(std::istream& in) : csv_(in, kReferenceColumns, "reference") {
    advance();
  }

  // Whether another image follows the one just returned. Exact, not a guess: the reader
  // already holds the next row. This is what lets the last *compared* image be sampled in
  // a single pass -- the alternative, re-rendering a ladder at every image so the most
  // recent one is always in hand, would cost 2.3M renders on a BTCUSDT day.
  bool has_more() const { return has_; }

  bool next(ReferenceImage& image) {
    if (!has_) return false;
    image.timestamp = pending_.timestamp;
    image.bids.clear();
    image.asks.clear();
    image.rows = 0;

    while (has_ && pending_.timestamp == image.timestamp) {
      std::vector<Level>& side =
          pending_.side == Side::Bid ? image.bids : image.asks;
      // Levels must arrive best-first and contiguous. The vendor drops *trailing* levels
      // when the book is thinner than 25 (D-014); a hole in the middle would mean the
      // export or its sort is wrong, and silently appending would turn that into a
      // plausible book at the wrong ranks.
      if (pending_.level != static_cast<std::int64_t>(side.size())) {
        throw ValidationError("reference image at " + std::to_string(image.timestamp) +
                              " has level " + std::to_string(pending_.level) + " where " +
                              std::to_string(side.size()) + " was expected: rows must be "
                              "ordered by (timestamp, side, level)");
      }
      side.push_back(Level{pending_.price, pending_.quantity});
      ++image.rows;
      advance();
    }
    return true;
  }

 private:
  struct Row {
    std::int64_t timestamp = 0;
    Side side = Side::Bid;
    std::int64_t level = 0;
    double price = 0.0;
    double quantity = 0.0;
  };

  void advance() {
    const std::vector<std::string_view>* fields = csv_.next();
    if (fields == nullptr) {
      has_ = false;
      return;
    }
    pending_.timestamp = parse_int((*fields)[0], "reference timestamp");
    pending_.side = parse_side((*fields)[1]);
    pending_.level = parse_int((*fields)[2], "reference level");
    pending_.price = parse_double((*fields)[3], "reference price");
    pending_.quantity = parse_double((*fields)[4], "reference quantity");
    has_ = true;
  }

  CsvReader csv_;
  Row pending_;
  bool has_ = false;
};

constexpr std::int64_t kMsPerDay = 86'400'000;

// Start of the UTC day containing `timestamp`, in epoch ms (D-013). The double modulo
// floors rather than truncates, so a pre-epoch timestamp would not round the wrong way --
// unreachable with real data, and cheap enough not to reason about twice (C14).
std::int64_t utc_day_start(std::int64_t timestamp) {
  return timestamp - ((timestamp % kMsPerDay) + kMsPerDay) % kMsPerDay;
}

}  // namespace

ValidationSummary validate(std::istream& events, std::istream& reference,
                           const ValidationOptions& options) {
  ValidationSummary summary;
  EventStream stream(events);
  ReferenceStream images(reference);
  BookReplayer replayer;
  ReferenceImage image;

  // Clean-run samples: open, midday, close. Held rather than printed, because whether the
  // run is clean is only known once it ends -- and on a failing run these would bury the
  // ladders that explain the failure. Three strings, not three books.
  std::vector<std::string> clean_renders;
  std::int64_t midday_target = 0;
  bool sampled_open = false;
  bool sampled_midday = false;

  while (images.next(image)) {
    ++summary.images;
    summary.reference_rows += image.rows;

    // Apply everything strictly before this image. State compared against an image at T is
    // built from rows at or before T and nothing after -- the replay cannot look ahead.
    while (stream.has() && stream.peek().timestamp < image.timestamp) {
      replayer.apply(stream.peek());
      stream.advance();
    }

    // Then the group sharing the image's millisecond, counting it: the count is what makes
    // the pairing unambiguous or not.
    std::int64_t group = 0;
    while (stream.has() && stream.peek().timestamp == image.timestamp) {
      replayer.apply(stream.peek());
      stream.advance();
      ++group;
    }

    const BookDiff diff =
        compare_top_n(replayer.book(), image.bids, image.asks, options.depth);

    if (group == 0) {
      ++summary.orphan_images;
      continue;
    }

    // Sampling for the clean-run rendering, in the same single pass. "Evenly spaced" is not
    // computable here -- the last image's timestamp is unknown until the stream ends -- so
    // the targets are wall-clock, taken from the UTC day the first compared image falls in.
    // Only compared images are eligible: rendering an orphan would show a book that nothing
    // checked. If the final image happens to be an orphan there is no close sample and the
    // run reports two, which is the honest outcome rather than a third invented one.
    if (options.diagnostics != nullptr) {
      const char* label = nullptr;
      if (!sampled_open) {
        midday_target = utc_day_start(image.timestamp) + kMsPerDay / 2;
        sampled_open = true;
        label = "open";
      } else if (!sampled_midday && image.timestamp >= midday_target) {
        sampled_midday = true;
        label = "midday";
      } else if (!images.has_more()) {
        label = "close";
      }
      if (label != nullptr) {
        clean_renders.push_back("sample " + std::string(label) + " at " +
                                std::to_string(image.timestamp) + "\n" +
                                format_ladder(replayer.book(), options.depth));
        summary.sample_clean_timestamps.push_back(image.timestamp);
      }
    }

    if (group > 1) {
      ++summary.ambiguous_images;
      if (!diff.empty()) {
        ++summary.ambiguous_mismatches;
        if (summary.sample_ambiguous_timestamps.size() < options.max_sample_mismatches) {
          summary.sample_ambiguous_timestamps.push_back(image.timestamp);
          if (options.diagnostics != nullptr) {
            // The caveat is the harness's to print, not the renderer's: ambiguity is a
            // property of how events were paired to this image, not of the levels that
            // differ. Without it a reader chases a replay defect that may not exist.
            *options.diagnostics << "ambiguous mismatch at " << image.timestamp << " ("
                                 << group << " events share this ms)\n"
                                 << "  AMBIGUOUS PAIRING: their order relative to the image is "
                                    "unrecoverable at ms resolution (D-013), so an ordering "
                                    "artefact is as likely here as a replay defect\n"
                                 << format_diff(diff, replayer.book(), image.bids, image.asks,
                                                options.depth);
          }
        }
      }
      continue;
    }

    ++summary.unambiguous_images;
    if (diff.empty()) continue;

    ++summary.unambiguous_mismatches;
    for (const LevelDiff& level : diff.differences) {
      switch (level.kind) {
        case DiffKind::PriceMismatch:
          ++summary.price_mismatches;
          break;
        case DiffKind::QuantityMismatch:
          ++summary.quantity_mismatches;
          break;
        case DiffKind::MissingLevel:
          ++summary.missing_levels;
          break;
        case DiffKind::ExtraLevel:
          ++summary.extra_levels;
          break;
      }
    }
    if (summary.sample_mismatch_timestamps.size() < options.max_sample_mismatches) {
      summary.sample_mismatch_timestamps.push_back(image.timestamp);
      if (options.diagnostics != nullptr) {
        *options.diagnostics << "mismatch at " << image.timestamp
                             << " (1 event in this ms, pairing forced)\n"
                             << format_diff(diff, replayer.book(), image.bids, image.asks,
                                            options.depth);
      }
    }
  }

  // Events after the last image still belong to the replay's statistics.
  while (stream.has()) {
    replayer.apply(stream.peek());
    stream.advance();
  }

  summary.replay = replayer.stats();
  summary.events = replayer.stats().applied;

  // Only on a clean run. On a failing one these would push the ladders that explain the
  // failure off the top of the screen, and the failure is what the reader came for.
  if (summary.verdict() != ValidationSummary::Verdict::Pass) {
    // Nothing was rendered, so nothing may be reported as rendered. Leaving these in would
    // put timestamps in the summary that no reader can find output for, and the summary is
    // the artifact a later reader trusts about a run they did not watch.
    summary.sample_clean_timestamps.clear();
  } else if (options.diagnostics != nullptr) {
    *options.diagnostics << "no mismatches; " << clean_renders.size()
                         << " sampled timestamp(s) rendered below so a passing run still "
                            "shows its work\n";
    for (const std::string& render : clean_renders) {
      *options.diagnostics << render;
    }
  }
  return summary;
}

ValidationSummary validate_files(const std::string& events_path,
                                 const std::string& reference_path,
                                 const ValidationOptions& options) {
  std::ifstream events(events_path);
  if (!events) throw ValidationError("cannot open events csv: " + events_path);
  std::ifstream reference(reference_path);
  if (!reference) throw ValidationError("cannot open reference csv: " + reference_path);
  return validate(events, reference, options);
}

void write_json(const ValidationSummary& summary, std::ostream& out) {
  const char* verdict = "inconclusive";
  if (summary.verdict() == ValidationSummary::Verdict::Pass) verdict = "pass";
  if (summary.verdict() == ValidationSummary::Verdict::Fail) verdict = "fail";

  out << "{\n";
  out << "  \"verdict\": \"" << verdict << "\",\n";
  out << "  \"passed\": " << (summary.passed() ? "true" : "false") << ",\n";
  out << "  \"events\": " << summary.events << ",\n";
  out << "  \"reference_rows\": " << summary.reference_rows << ",\n";
  out << "  \"images\": " << summary.images << ",\n";
  out << "  \"unambiguous_images\": " << summary.unambiguous_images << ",\n";
  out << "  \"ambiguous_images\": " << summary.ambiguous_images << ",\n";
  out << "  \"orphan_images\": " << summary.orphan_images << ",\n";
  out << "  \"unambiguous_mismatches\": " << summary.unambiguous_mismatches << ",\n";
  out << "  \"ambiguous_mismatches\": " << summary.ambiguous_mismatches << ",\n";
  out << "  \"price_mismatches\": " << summary.price_mismatches << ",\n";
  out << "  \"quantity_mismatches\": " << summary.quantity_mismatches << ",\n";
  out << "  \"missing_levels\": " << summary.missing_levels << ",\n";
  out << "  \"extra_levels\": " << summary.extra_levels << ",\n";
  out << "  \"replay\": {\n";
  out << "    \"applied\": " << summary.replay.applied << ",\n";
  out << "    \"snapshot_rows\": " << summary.replay.snapshot_rows << ",\n";
  out << "    \"resyncs\": " << summary.replay.resyncs << ",\n";
  out << "    \"removals\": " << summary.replay.removals << ",\n";
  out << "    \"crossed\": " << summary.replay.crossed << ",\n";
  out << "    \"last_timestamp\": " << summary.replay.last_timestamp << "\n";
  out << "  },\n";
  out << "  \"sample_mismatch_timestamps\": [";
  for (std::size_t i = 0; i < summary.sample_mismatch_timestamps.size(); ++i) {
    if (i != 0) out << ", ";
    out << summary.sample_mismatch_timestamps[i];
  }
  out << "],\n";
  out << "  \"sample_ambiguous_timestamps\": [";
  for (std::size_t i = 0; i < summary.sample_ambiguous_timestamps.size(); ++i) {
    if (i != 0) out << ", ";
    out << summary.sample_ambiguous_timestamps[i];
  }
  out << "],\n";
  out << "  \"sample_clean_timestamps\": [";
  for (std::size_t i = 0; i < summary.sample_clean_timestamps.size(); ++i) {
    if (i != 0) out << ", ";
    out << summary.sample_clean_timestamps[i];
  }
  out << "]\n";
  out << "}\n";
}

}  // namespace perpcarry::tools
