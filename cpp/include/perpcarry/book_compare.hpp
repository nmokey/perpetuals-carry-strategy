// Top-N comparison of a replayed book against an independent reference image.
// See docs/specs/M2/M2-T2-book-replay.md.
//
// This task owns the comparison and its verdict; M2-T3 owns rendering it. The result is
// structured rather than boolean because "which level, and in what way" is the difference
// between a debuggable failure and a re-run.
#ifndef PERPCARRY_BOOK_COMPARE_HPP
#define PERPCARRY_BOOK_COMPARE_HPP

#include <cstddef>
#include <cstdint>
#include <span>
#include <vector>

#include "perpcarry/order_book.hpp"

namespace perpcarry {

enum class DiffKind : std::uint8_t {
  PriceMismatch,     // both books have this rank; the prices differ
  QuantityMismatch,  // both books have this rank at the same price; the sizes differ
  MissingLevel,      // the reference has this rank, the replayed book does not
  ExtraLevel,        // the replayed book has this rank, the reference does not
};

struct LevelDiff {
  Side side;
  std::size_t rank;  // 0-based, best first
  DiffKind kind;
  Level replayed;   // {0, 0} when kind == MissingLevel
  Level reference;  // {0, 0} when kind == ExtraLevel
};

struct BookDiff {
  std::vector<LevelDiff> differences;

  bool empty() const { return differences.empty(); }
  std::size_t size() const { return differences.size(); }
};

// Ranks a top-`depth` comparison can speak about at all, given how many levels each side
// holds. Past `depth` the reference says nothing, and our ~1000-level book against a
// 25-level image is the expected shape rather than a defect.
//
// Exported rather than kept private because M2-T3's renderer must draw exactly the window
// this function compared. A renderer that recomputed the same rule would be a second
// source of truth that can only ever agree by luck, and would disagree in the direction
// that looks like success -- a diff quietly omitting the rank that differs (C15).
std::size_t compared_rank_count(std::size_t replayed_levels, std::size_t reference_levels,
                                std::size_t depth);

// Compares the top `depth` levels per side.
//
// Equality is exact, with no tolerance, and that is deliberate: both sides hold float64
// values that were only ever copied from the vendor's own decimal text, never computed, so
// there is no arithmetic between them for an epsilon to absorb. A tolerance introduced to
// make a book comparison pass is how "calibrated from real data" quietly becomes
// "calibrated from data that nearly matches real data".
//
// A replayed side thinner than the reference is a MissingLevel mismatch, not a pass by
// omission: the replayed book is ~1000 levels deep, so a thin side means state was lost.
// Conversely the reference drops trailing levels that do not exist (D-014), so a replayed
// level where the reference has none is an ExtraLevel -- a phantom.
BookDiff compare_top_n(const OrderBook& book, std::span<const Level> reference_bids,
                       std::span<const Level> reference_asks, std::size_t depth);

}  // namespace perpcarry

#endif  // PERPCARRY_BOOK_COMPARE_HPP
