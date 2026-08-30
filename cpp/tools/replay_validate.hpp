// The M2-T2 validation harness: replay an exported symbol-day and compare every reference
// image against the replayed book. See docs/specs/M2/M2-T2-book-replay.md and D-018.
//
// This lives in cpp/tools/, NOT in perpcarry_core, because it does file I/O and the core
// does none (D-012). It is a local developer tool: its input is raw vendor book data,
// which may never enter CI or the repository (Tardis Clause 9.2(2)).
#ifndef PERPCARRY_TOOLS_REPLAY_VALIDATE_HPP
#define PERPCARRY_TOOLS_REPLAY_VALIDATE_HPP

#include <cstdint>
#include <iosfwd>
#include <string>
#include <vector>

#include "perpcarry/book_compare.hpp"
#include "perpcarry/book_replayer.hpp"

namespace perpcarry::tools {

// Why the comparison points are partitioned rather than given a tolerance.
//
// Measured on 0GUSDT 2026-06-01: the vendor emits a reference image on book change, so
// every one of its 277,590 images shares a millisecond with the diff that produced it --
// there are no quiet points to compare at, none even with a +/-10 ms gap. Meanwhile our
// own ingest truncated microseconds to milliseconds (D-013), so when several diffs share
// an image's millisecond their order relative to that image is unrecoverable from the
// corpus.
//
// So: where an image's millisecond holds exactly one event the pairing is forced and
// equality must be exact (37.9% of images, 105,142 of them, on that day). Everything else
// is counted and reported, never asserted -- an epsilon wide enough to absorb it would be
// wide enough to hide a real defect.
struct ValidationSummary {
  std::int64_t events = 0;
  std::int64_t reference_rows = 0;
  std::int64_t images = 0;

  std::int64_t unambiguous_images = 0;
  std::int64_t ambiguous_images = 0;
  std::int64_t orphan_images = 0;  // no event shares the image's millisecond

  std::int64_t unambiguous_mismatches = 0;
  std::int64_t ambiguous_mismatches = 0;

  // Mismatching levels by category, over the unambiguous set only.
  std::int64_t price_mismatches = 0;
  std::int64_t quantity_mismatches = 0;
  std::int64_t missing_levels = 0;
  std::int64_t extra_levels = 0;

  BookReplayer::Stats replay;

  // Timestamps of the first few mismatches, for inspection. Bounded because a systematic
  // defect would otherwise report every image in the day and bury the first -- which is
  // the informative one. Ambiguous mismatches are sampled too: they are not assertable,
  // but a rate that is *nearly* zero is a thing to explain, and it cannot be explained
  // without a timestamp to look at.
  std::vector<std::int64_t> sample_mismatch_timestamps;
  std::vector<std::int64_t> sample_ambiguous_timestamps;

  enum class Verdict { Pass, Fail, Inconclusive };

  // Passing requires every image to match, ambiguous ones included (D-019).
  //
  // The original criterion asserted only on the unambiguous subset, which is sound with no
  // assumption at all. It had to be revised because on a liquid symbol that subset is
  // *empty*: BTCUSDT 2026-06-01 has zero unambiguous images against 0GUSDT's 105,142,
  // since every image there shares its millisecond with several events. A criterion that
  // cannot be evaluated on the symbol M2-M4 actually replays is not a criterion.
  //
  // Asserting on the ambiguous set adds one assumption -- that the vendor emits an image
  // only after applying the whole millisecond group -- and that assumption now rests on
  // 564,783 images across two symbols with zero counter-examples. Note the direction: this
  // makes the check stricter, not looser. If the assumption is ever false, a run fails
  // loudly and gets investigated, which is the safe way to be wrong.
  //
  // Inconclusive means nothing was compared. A run that compared nothing must never report
  // success (C15).
  Verdict verdict() const {
    if (images == 0) return Verdict::Inconclusive;
    return (unambiguous_mismatches == 0 && ambiguous_mismatches == 0) ? Verdict::Pass
                                                                     : Verdict::Fail;
  }

  bool passed() const { return verdict() == Verdict::Pass; }
};

struct ValidationOptions {
  std::size_t depth = 25;               // the reference is book_snapshot_25
  std::size_t max_sample_mismatches = 5;
  // When set, the first mismatching image also gets its diff rendered here (M2-T3 will
  // replace this with a ladder; T2 only needs the verdict).
  std::ostream* diagnostics = nullptr;
};

class ValidationError : public std::runtime_error {
 public:
  explicit ValidationError(const std::string& what) : std::runtime_error(what) {}
};

// Streams both CSVs, replays, and compares. Neither file is held whole: a BTCUSDT day is
// 161M events, so anything that materialised the input would decide the tool's usable
// scale rather than the machine's.
ValidationSummary validate(std::istream& events, std::istream& reference,
                           const ValidationOptions& options = {});

ValidationSummary validate_files(const std::string& events_path,
                                 const std::string& reference_path,
                                 const ValidationOptions& options = {});

// Machine-readable summary. This -- and only this -- is what may be committed from a real
// run: counts and rates expose no raw rows and cannot reconstruct a book.
void write_json(const ValidationSummary& summary, std::ostream& out);

}  // namespace perpcarry::tools

#endif  // PERPCARRY_TOOLS_REPLAY_VALIDATE_HPP
