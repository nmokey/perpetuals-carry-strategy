// L2 price-level order book state. See docs/specs/M2/M2-T1-order-book-core.md.
//
// This is the structure every downstream number is computed from: M4's impact simulator
// walks it to produce a realized fill price, which is what makes "execution costs are
// calibrated, not assumed" true rather than decorative. A subtly wrong book yields a
// plausible-looking slippage figure that nothing downstream can detect.
#ifndef PERPCARRY_ORDER_BOOK_HPP
#define PERPCARRY_ORDER_BOOK_HPP

#include <cstddef>
#include <cstdint>
#include <optional>
#include <span>
#include <vector>

namespace perpcarry {

enum class Side : std::uint8_t { Bid = 0, Ask = 1 };

struct Level {
  double price;
  double quantity;
};

// One price level of aggregated resting size. There is no order id anywhere in this
// header, and that is a property of the data rather than an omission: the only reachable
// book source is price-level aggregated at source (OD-5 / D-017), so queue position is
// unknowable and M4 can model marketable orders only.
class OrderBook {
 public:
  // Levels a side is expected to hold. Measured 2026-08-22 on the opening snapshot of
  // 2026-06-01: 1013 bid / 1002 ask for BTCUSDT, 403 / 1000 for 0GUSDT -- the feed caps
  // around 1000 per side. Reserving here keeps steady-state replay allocation-free after
  // warmup, which matters mainly for removing noise from any later measurement.
  static constexpr std::size_t kInitialLevelCapacity = 2048;

  OrderBook();

  // Applies one update. `quantity == 0` removes the level -- 11% of a real day's feed is
  // removals, so this is the common path, not an edge case. Removing a price that is not
  // in the book is a no-op: BTCUSDT's opening *snapshot* block carries 13 zero-quantity
  // rows, so treating it as an error cannot ingest the first 2015 rows of a real day.
  //
  // Throws std::invalid_argument for a non-finite or non-positive price, or a non-finite
  // or negative quantity.
  void apply(Side side, double price, double quantity);

  // Empties both sides, keeping capacity. Used by the replayer on a snapshot block.
  void clear();

  std::optional<Level> best(Side side) const;
  std::optional<Level> best_bid() const;
  std::optional<Level> best_ask() const;

  // True when both sides are populated and best bid >= best ask. An aggregated L2 feed
  // shows this transiently when the two sides' updates arrive out of order, so it is
  // reported rather than repaired: silently correcting it would erase the cheapest signal
  // that a replay has gone wrong.
  bool is_crossed() const;

  // Number of levels on a side -- a count, not a quantity. M4's "depth" is the quantity
  // sense; this deliberately does not share the word.
  std::size_t level_count(Side side) const;

  // Contiguous, ordered best to worst: bids descending by price, asks ascending. The span
  // is what M4-T1 iterates on every simulated order, so the book walk needs no copy and no
  // allocation. Invalidated by the next apply() or clear().
  std::span<const Level> levels(Side side) const;

 private:
  std::vector<Level>& side_levels(Side side);
  const std::vector<Level>& side_levels(Side side) const;

  std::vector<Level> bids_;
  std::vector<Level> asks_;
};

}  // namespace perpcarry

#endif  // PERPCARRY_ORDER_BOOK_HPP
