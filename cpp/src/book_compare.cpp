#include "perpcarry/book_compare.hpp"

#include <algorithm>

namespace perpcarry {
namespace {

void compare_side(const OrderBook& book, Side side, std::span<const Level> reference,
                  std::size_t depth, std::vector<LevelDiff>& out) {
  const std::span<const Level> replayed = book.levels(side);

  // Ranks the comparison can speak about at all: past `depth` the reference says nothing,
  // and our ~1000-level book against a 25-level image is the expected shape rather than a
  // defect. Within that window, a rank the reference omits is one it asserts does not
  // exist (D-014 drops trailing levels only when the book really was thinner).
  const std::size_t limit = std::min(depth, std::max(replayed.size(), reference.size()));

  for (std::size_t rank = 0; rank < limit; ++rank) {
    const bool has_replayed = rank < replayed.size();
    const bool has_reference = rank < reference.size();

    if (has_replayed && has_reference) {
      if (replayed[rank].price != reference[rank].price) {
        out.push_back(
            LevelDiff{side, rank, DiffKind::PriceMismatch, replayed[rank], reference[rank]});
      } else if (replayed[rank].quantity != reference[rank].quantity) {
        out.push_back(
            LevelDiff{side, rank, DiffKind::QuantityMismatch, replayed[rank], reference[rank]});
      }
    } else if (has_reference) {
      out.push_back(LevelDiff{side, rank, DiffKind::MissingLevel, Level{0.0, 0.0}, reference[rank]});
    } else {
      out.push_back(LevelDiff{side, rank, DiffKind::ExtraLevel, replayed[rank], Level{0.0, 0.0}});
    }
  }
}

}  // namespace

BookDiff compare_top_n(const OrderBook& book, std::span<const Level> reference_bids,
                       std::span<const Level> reference_asks, std::size_t depth) {
  BookDiff diff;
  compare_side(book, Side::Bid, reference_bids, depth, diff.differences);
  compare_side(book, Side::Ask, reference_asks, depth, diff.differences);
  return diff;
}

}  // namespace perpcarry
