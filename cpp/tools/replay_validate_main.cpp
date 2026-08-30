// perpcarry_replay_validate -- M2-T2's local validation harness (D-018).
//
//   uv run python -m perpcarry.tools.export_book --symbol 0GUSDT --date 2026-06-01
//   ./build/dev/cpp/tools/perpcarry_replay_validate <dir>/events.csv <dir>/reference.csv
//
// Its input is licensed vendor book data: never commit it, never let it reach CI. The JSON
// summary is the only publishable output (Tardis Clause 9.2(2)).
#include <exception>
#include <fstream>
#include <iostream>
#include <string>

#include "replay_validate.hpp"

int main(int argc, char** argv) {
  if (argc < 3 || argc > 4) {
    std::cerr << "usage: " << argv[0] << " EVENTS_CSV REFERENCE_CSV [SUMMARY_JSON]\n";
    return 2;
  }

  perpcarry::tools::ValidationOptions options;
  options.diagnostics = &std::cout;

  try {
    const perpcarry::tools::ValidationSummary summary =
        perpcarry::tools::validate_files(argv[1], argv[2], options);

    perpcarry::tools::write_json(summary, std::cout);

    if (argc == 4) {
      std::ofstream json(argv[3]);
      if (!json) {
        std::cerr << "error: cannot write summary to " << argv[3] << "\n";
        return 2;
      }
      perpcarry::tools::write_json(summary, json);
    }

    using Verdict = perpcarry::tools::ValidationSummary::Verdict;
    if (summary.verdict() == Verdict::Inconclusive) {
      // Reporting "no mismatches" for a run that compared nothing would be reporting that
      // nothing was checked.
      std::cerr << "INCONCLUSIVE: no images were compared\n";
      return 3;
    }
    if (summary.verdict() == Verdict::Fail) {
      std::cerr << "FAILED: " << summary.unambiguous_mismatches << " of "
                << summary.unambiguous_images << " unambiguous image(s) and "
                << summary.ambiguous_mismatches << " of " << summary.ambiguous_images
                << " ambiguous image(s) differ\n";
      return 1;
    }
    std::cerr << "OK: " << summary.images << " image(s) matched exactly ("
              << summary.unambiguous_images << " with a forced pairing)\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "error: " << error.what() << "\n";
    return 2;
  }
}
