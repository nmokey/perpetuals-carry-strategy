// M2-T2 -- the validation harness itself.
// Spec: docs/specs/M2/M2-T2-book-replay.md, decision D-018.
//
// The real-data comparison can never run in CI: the vendor's licence forbids book rows
// reaching it, in the per-PR tier and the nightly one alike. What CI *can* enforce is that
// the mechanism works -- that a defect placed at a known timestamp is found and reported
// there. So only the input to this check is manual; the check itself is continuous.

#include <catch2/catch_test_macros.hpp>

#include <algorithm>
#include <cctype>
#include <sstream>
#include <string>

#include "perpcarry/book_debug.hpp"
#include "perpcarry/book_replayer.hpp"
#include "replay_validate.hpp"

using perpcarry::BookReplayError;
using perpcarry::tools::validate;
using perpcarry::tools::ValidationError;
using perpcarry::tools::ValidationOptions;
using perpcarry::tools::ValidationSummary;

namespace {

// Quoted exactly as pyarrow's CSV writer emits it, so the parser is exercised against the
// shape the exporter really produces rather than a convenient one.
const char* kEvents =
    "\"timestamp\",\"local_timestamp\",\"is_snapshot\",\"side\",\"price\",\"quantity\"\n"
    "1000,1002,true,\"bid\",100.0,5.0\n"
    "1000,1002,true,\"bid\",99.0,6.0\n"
    "1000,1002,true,\"ask\",101.0,7.0\n"
    "1000,1002,true,\"ask\",102.0,8.0\n"
    "1001,1003,false,\"bid\",100.0,4.0\n"
    "1002,1004,false,\"ask\",101.0,0.0\n"
    "1003,1005,false,\"bid\",98.0,3.0\n"
    "1003,1005,false,\"bid\",97.0,2.0\n"
    "1004,1006,false,\"bid\",100.0,0.0\n";

// Images at 1001, 1002, 1003 and 1004. 1003 holds two events, so its pairing is ambiguous
// and it is reported rather than asserted on.
const char* kReference =
    "\"timestamp\",\"side\",\"level\",\"price\",\"quantity\"\n"
    "1001,\"ask\",0,101.0,7.0\n"
    "1001,\"ask\",1,102.0,8.0\n"
    "1001,\"bid\",0,100.0,4.0\n"
    "1001,\"bid\",1,99.0,6.0\n"
    "1002,\"ask\",0,102.0,8.0\n"
    "1002,\"bid\",0,100.0,4.0\n"
    "1002,\"bid\",1,99.0,6.0\n"
    "1003,\"ask\",0,102.0,8.0\n"
    "1003,\"bid\",0,100.0,4.0\n"
    "1003,\"bid\",1,99.0,6.0\n"
    "1003,\"bid\",2,98.0,3.0\n"
    "1003,\"bid\",3,97.0,2.0\n"
    "1004,\"ask\",0,102.0,8.0\n"
    "1004,\"bid\",0,99.0,6.0\n"
    "1004,\"bid\",1,98.0,3.0\n"
    "1004,\"bid\",2,97.0,2.0\n";

ValidationSummary run(const std::string& events, const std::string& reference) {
  std::istringstream event_stream(events);
  std::istringstream reference_stream(reference);
  return validate(event_stream, reference_stream, ValidationOptions{});
}

std::string with_replacement(const char* text, const std::string& from, const std::string& to) {
  std::string out(text);
  const std::size_t at = out.find(from);
  REQUIRE(at != std::string::npos);
  out.replace(at, from.size(), to);
  return out;
}

}  // namespace

TEST_CASE("a clean export validates, and checks more than three timestamps", "[validate]") {
  const ValidationSummary summary = run(kEvents, kReference);

  REQUIRE(summary.passed());
  REQUIRE(summary.images == 4);
  REQUIRE(summary.unambiguous_images == 3);  // 1001, 1002, 1004
  REQUIRE(summary.ambiguous_images == 1);    // 1003 shares its ms with two events
  REQUIRE(summary.orphan_images == 0);
  REQUIRE(summary.unambiguous_mismatches == 0);
  REQUIRE(summary.ambiguous_mismatches == 0);
  REQUIRE(summary.events == 9);
  REQUIRE(summary.reference_rows == 16);
  REQUIRE(summary.replay.snapshot_rows == 4);
  REQUIRE(summary.replay.removals == 2);
  REQUIRE(summary.replay.resyncs == 0);
}

TEST_CASE("a defect at a known timestamp is found and reported", "[validate]") {
  SECTION("a wrong size in the reference is caught as a quantity mismatch") {
    const std::string reference =
        with_replacement(kReference, "1002,\"bid\",0,100.0,4.0", "1002,\"bid\",0,100.0,4.5");
    const ValidationSummary summary = run(kEvents, reference);

    REQUIRE_FALSE(summary.passed());
    REQUIRE(summary.unambiguous_mismatches == 1);
    REQUIRE(summary.quantity_mismatches == 1);
    REQUIRE(summary.price_mismatches == 0);
    REQUIRE(summary.sample_mismatch_timestamps == std::vector<std::int64_t>{1002});
    // The other two unambiguous images still matched -- one defect is not a total failure.
    REQUIRE(summary.unambiguous_images == 3);
  }

  SECTION("a dropped diff shows up as the level it failed to remove") {
    const std::string events =
        with_replacement(kEvents, "1002,1004,false,\"ask\",101.0,0.0\n", "");
    const ValidationSummary summary = run(events, kReference);

    REQUIRE_FALSE(summary.passed());
    // 101.0 lingers at ask rank 0 from here on, so the ask side is off by one rank.
    REQUIRE(summary.unambiguous_mismatches >= 1);

    // Deleting the event also deletes the image's pairing partner: 1002 now has no event
    // in its millisecond at all, so it is an orphan rather than an unambiguous point, and
    // the first *assertable* mismatch is the next one. This is why orphans are counted
    // separately instead of being folded into either bucket -- which image is unambiguous
    // is a property of the data, not a fixed set decided in advance.
    REQUIRE(summary.orphan_images == 1);
    REQUIRE(summary.sample_mismatch_timestamps.front() == 1004);
  }

  SECTION("a level the reference says does not exist is an extra level") {
    const std::string reference =
        with_replacement(kReference, "1004,\"bid\",2,97.0,2.0\n", "");
    const ValidationSummary summary = run(kEvents, reference);

    REQUIRE_FALSE(summary.passed());
    REQUIRE(summary.extra_levels == 1);
    REQUIRE(summary.sample_mismatch_timestamps == std::vector<std::int64_t>{1004});
  }
}

TEST_CASE("ambiguous mismatches fail the run but stay separately counted", "[validate]") {
  // 1003 shares its millisecond with two events, so the pairing is not forced. It is still
  // asserted on (D-019): the unambiguous subset is empty on liquid symbols, so a criterion
  // resting only on it cannot be evaluated where it matters most. The counts stay split so
  // the sound core -- the images whose pairing *is* forced -- remains visible.
  const std::string reference =
      with_replacement(kReference, "1003,\"bid\",2,98.0,3.0", "1003,\"bid\",2,98.0,3.5");
  const ValidationSummary summary = run(kEvents, reference);

  REQUIRE(summary.ambiguous_mismatches == 1);
  REQUIRE(summary.unambiguous_mismatches == 0);
  REQUIRE_FALSE(summary.passed());
  REQUIRE(summary.verdict() == ValidationSummary::Verdict::Fail);
  REQUIRE(summary.sample_ambiguous_timestamps == std::vector<std::int64_t>{1003});
}

TEST_CASE("a run that compares nothing is inconclusive, not a pass", "[validate]") {
  const char* no_images = "\"timestamp\",\"side\",\"level\",\"price\",\"quantity\"\n";
  const ValidationSummary summary = run(kEvents, no_images);

  REQUIRE(summary.images == 0);
  REQUIRE(summary.verdict() == ValidationSummary::Verdict::Inconclusive);
  REQUIRE_FALSE(summary.passed());
  // The replay still happened -- the events were consumed, there was just nothing to check
  // them against.
  REQUIRE(summary.events == 9);
}

// M2-T3 replaced the one-line-per-level stopgap this test was written against with a
// ladder. Migrated rather than deleted: it is the only check that the diagnostics stream is
// wired up at all, and a renderer nothing calls is worth exactly as much as no renderer.
TEST_CASE("the diagnostics stream renders a ladder around the level that differs",
          "[validate]") {
  const std::string reference =
      with_replacement(kReference, "1002,\"bid\",0,100.0,4.0", "1002,\"bid\",0,100.0,4.5");
  std::istringstream events(kEvents);
  std::istringstream reference_stream(reference);
  std::ostringstream diagnostics;

  ValidationOptions options;
  options.diagnostics = &diagnostics;
  const ValidationSummary summary = validate(events, reference_stream, options);

  REQUIRE_FALSE(summary.passed());
  const std::string text = diagnostics.str();
  REQUIRE(text.find("mismatch at 1002") != std::string::npos);
  REQUIRE(text.find("! quantity") != std::string::npos);
  REQUIRE(text.find("replayed_price") != std::string::npos);

  // The point of the ladder over the stopgap: the level that differs arrives with the
  // levels around it, which are usually what explains it. Rank 1 matched and is still here.
  REQUIRE(text.find("99.0") != std::string::npos);
  REQUIRE(text.find("--- spread ") != std::string::npos);
}

// M2-T3, the "3+ sample timestamps" half of the criterion. Timestamps span a real UTC day
// because the sampling rule is wall-clock: open, midday, close. A fixture spanning four
// milliseconds would never reach the midday target and would silently test only two of the
// three cases.
const std::int64_t kDayStart = 1780272000000;  // 2026-06-01T00:00:00Z

// The day's first image lands a little after midnight, never exactly on it -- which is what
// a real export looks like, and what makes the wall-clock rule observable. Anchored to the
// UTC day, the midday target is 12:00:00.000 whatever time the feed opened; anchored to the
// first image instead, it would drift by that offset and the midday image would be missed.
// A fixture opening at exactly 00:00:00.000 cannot tell those two rules apart.
const std::int64_t kOpen = kDayStart + 137;
const std::int64_t kMidday = kDayStart + 43200000;
const std::int64_t kEvening = kDayStart + 72000000;

std::string day_events() {
  return "\"timestamp\",\"local_timestamp\",\"is_snapshot\",\"side\",\"price\",\"quantity\"\n" +
         std::to_string(kOpen) + ",1,true,\"bid\",100.0,5.0\n" + std::to_string(kOpen) +
         ",1,true,\"ask\",101.0,7.0\n" + std::to_string(kMidday) + ",2,false,\"bid\",100.0,6.0\n" +
         std::to_string(kEvening) + ",3,false,\"ask\",101.0,8.0\n";
}

std::string day_reference(double midday_bid_quantity = 6.0) {
  return "\"timestamp\",\"side\",\"level\",\"price\",\"quantity\"\n" + std::to_string(kOpen) +
         ",\"ask\",0,101.0,7.0\n" + std::to_string(kOpen) + ",\"bid\",0,100.0,5.0\n" +
         std::to_string(kMidday) + ",\"ask\",0,101.0,7.0\n" + std::to_string(kMidday) +
         ",\"bid\",0,100.0," + perpcarry::format_price(midday_bid_quantity) + "\n" +
         std::to_string(kEvening) + ",\"ask\",0,101.0,8.0\n" + std::to_string(kEvening) +
         ",\"bid\",0,100.0,6.0\n";
}

TEST_CASE("a clean run renders three sampled timestamps", "[validate]") {
  std::istringstream events(day_events());
  std::istringstream reference(day_reference());
  std::ostringstream diagnostics;

  ValidationOptions options;
  options.diagnostics = &diagnostics;
  const ValidationSummary summary = validate(events, reference, options);

  REQUIRE(summary.passed());
  REQUIRE(summary.sample_clean_timestamps.size() == 3);
  REQUIRE(summary.sample_clean_timestamps[0] == kOpen);
  REQUIRE(summary.sample_clean_timestamps[1] == kMidday);
  REQUIRE(summary.sample_clean_timestamps[2] == kEvening);

  // And they are rendered, not merely counted: a pass that printed nothing looks the same
  // as a pass that compared nothing (C15).
  const std::string text = diagnostics.str();
  REQUIRE(text.find("sample open at " + std::to_string(kOpen)) != std::string::npos);
  REQUIRE(text.find("sample midday at " + std::to_string(kMidday)) != std::string::npos);
  REQUIRE(text.find("sample close at " + std::to_string(kEvening)) != std::string::npos);
  REQUIRE(text.find("book: top 25 of 1 bid / 1 ask") != std::string::npos);
}

TEST_CASE("a defect at a known timestamp is rendered as a ladder at that timestamp",
          "[validate]") {
  std::istringstream events(day_events());
  std::istringstream reference(day_reference(6.5));  // the midday image disagrees
  std::ostringstream diagnostics;

  ValidationOptions options;
  options.diagnostics = &diagnostics;
  const ValidationSummary summary = validate(events, reference, options);

  REQUIRE_FALSE(summary.passed());
  REQUIRE(summary.images == 3);  // three timestamps were compared, only one differs
  REQUIRE(summary.sample_mismatch_timestamps.size() == 1);
  REQUIRE(summary.sample_mismatch_timestamps[0] == kMidday);

  const std::string text = diagnostics.str();
  REQUIRE(text.find("mismatch at " + std::to_string(kMidday)) != std::string::npos);
  REQUIRE(text.find("! quantity") != std::string::npos);
  REQUIRE(text.find("6.5") != std::string::npos);

  // A failing run must not bury its ladders under the clean-run samples -- and must not
  // report samples it never printed. The summary is what a later reader trusts about a run
  // they did not watch, so a timestamp in it has to have output behind it.
  REQUIRE(text.find("sample open at ") == std::string::npos);
  REQUIRE(summary.sample_clean_timestamps.empty());
}

// write_json had no test at all before M2-T3 touched it, which is how a stray comma ships:
// the harness's own output is the one artifact of a real run that may be committed (D-018),
// and nothing was checking it was even parseable.
TEST_CASE("the JSON summary is well formed and carries the sampled timestamps", "[validate]") {
  std::istringstream events(day_events());
  std::istringstream reference(day_reference());
  std::ostringstream diagnostics;

  ValidationOptions options;
  options.diagnostics = &diagnostics;
  const ValidationSummary summary = validate(events, reference, options);

  std::ostringstream json;
  perpcarry::tools::write_json(summary, json);
  const std::string text = json.str();

  REQUIRE(text.find("\"sample_clean_timestamps\": [" + std::to_string(kOpen) + ", ") !=
          std::string::npos);
  REQUIRE(text.find("\"verdict\": \"pass\"") != std::string::npos);

  // Structural check, since there is no JSON parser here: every brace and bracket closes,
  // and no separator is left dangling before one -- the exact defect an added field invites.
  int depth = 0;
  char previous = '\0';
  for (const char c : text) {
    if (c == '{' || c == '[') ++depth;
    if (c == '}' || c == ']') {
      --depth;
      REQUIRE(previous != ',');
    }
    REQUIRE(depth >= 0);
    if (!std::isspace(static_cast<unsigned char>(c))) previous = c;
  }
  REQUIRE(depth == 0);
}

TEST_CASE("only an ambiguous mismatch carries the ambiguity caveat", "[validate]") {
  SECTION("ambiguous -- two events share the image's millisecond") {
    const std::string reference =
        with_replacement(kReference, "1003,\"bid\",2,98.0,3.0", "1003,\"bid\",2,98.0,3.5");
    std::istringstream events(kEvents);
    std::istringstream reference_stream(reference);
    std::ostringstream diagnostics;

    ValidationOptions options;
    options.diagnostics = &diagnostics;
    const ValidationSummary summary = validate(events, reference_stream, options);

    REQUIRE(summary.ambiguous_mismatches == 1);
    const std::string text = diagnostics.str();
    REQUIRE(text.find("ambiguous mismatch at 1003") != std::string::npos);
    REQUIRE(text.find("AMBIGUOUS PAIRING") != std::string::npos);
  }

  SECTION("unambiguous -- the pairing was forced, so no caveat") {
    const std::string reference =
        with_replacement(kReference, "1002,\"bid\",0,100.0,4.0", "1002,\"bid\",0,100.0,4.5");
    std::istringstream events(kEvents);
    std::istringstream reference_stream(reference);
    std::ostringstream diagnostics;

    ValidationOptions options;
    options.diagnostics = &diagnostics;
    const ValidationSummary summary = validate(events, reference_stream, options);

    REQUIRE(summary.unambiguous_mismatches == 1);
    const std::string text = diagnostics.str();
    REQUIRE(text.find("pairing forced") != std::string::npos);
    REQUIRE(text.find("AMBIGUOUS PAIRING") == std::string::npos);
  }
}

TEST_CASE("a malformed export is rejected rather than misread", "[validate]") {
  SECTION("a reordered header") {
    const std::string events = with_replacement(
        kEvents, "\"timestamp\",\"local_timestamp\",\"is_snapshot\",\"side\",\"price\",\"quantity\"",
        "\"timestamp\",\"local_timestamp\",\"is_snapshot\",\"side\",\"quantity\",\"price\"");
    REQUIRE_THROWS_AS(run(events, kReference), ValidationError);
  }

  SECTION("a hole in an image's levels") {
    // Trailing levels may be absent (D-014); a missing *middle* level means the export or
    // its sort is wrong, and appending would quietly place every later level one rank off.
    const std::string reference =
        with_replacement(kReference, "1003,\"bid\",2,98.0,3.0\n", "");
    REQUIRE_THROWS_AS(run(kEvents, reference), ValidationError);
  }

  SECTION("an empty file") {
    REQUIRE_THROWS_AS(run("", kReference), ValidationError);
  }

  SECTION("events that do not open with a snapshot") {
    const std::string events =
        with_replacement(kEvents, "1000,1002,true,\"bid\",100.0,5.0", "1000,1002,false,\"bid\",100.0,5.0");
    REQUIRE_THROWS_AS(run(events, kReference), BookReplayError);
  }

  SECTION("an unparseable price") {
    const std::string events =
        with_replacement(kEvents, "1001,1003,false,\"bid\",100.0,4.0", "1001,1003,false,\"bid\",abc,4.0");
    REQUIRE_THROWS_AS(run(events, kReference), ValidationError);
  }
}

TEST_CASE("prices round-trip through the exporter's number format", "[validate]") {
  // pyarrow writes shortest round-trip doubles, including exponent forms. Parsing these
  // back to a different double would make every comparison meaningless -- and would look
  // like a replay defect rather than a parsing one.
  const char* events =
      "\"timestamp\",\"local_timestamp\",\"is_snapshot\",\"side\",\"price\",\"quantity\"\n"
      "1000,1002,true,\"bid\",0.30000000000000004,1e-9\n"
      "1000,1002,true,\"ask\",1.7976931348623157e+308,5e-324\n";
  const char* reference =
      "\"timestamp\",\"side\",\"level\",\"price\",\"quantity\"\n"
      "1000,\"ask\",0,1.7976931348623157e+308,5e-324\n"
      "1000,\"bid\",0,0.30000000000000004,1e-9\n";

  const ValidationSummary summary = run(events, reference);
  REQUIRE(summary.unambiguous_images == 0);  // the image shares its ms with two events
  REQUIRE(summary.ambiguous_images == 1);
  REQUIRE(summary.ambiguous_mismatches == 0);  // exact equality held through the text
}
