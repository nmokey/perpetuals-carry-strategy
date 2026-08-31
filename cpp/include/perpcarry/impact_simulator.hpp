// Static book-walk execution simulator. See docs/specs/M4/M4-T1-static-book-walk.md.
//
// This is the function that makes "execution costs are calibrated, not assumed" either true or
// decorative: every downstream number, up to and including the capacity answer, is this walk
// repeated across sizes and times. A subtly wrong walk yields a plausible slippage figure that
// nothing downstream can detect.
//
// **Marketable orders only, and that is the data's limit rather than a simplification.** The only
// reachable book is price-level aggregated (OD-5 / D-017), so queue position is unknowable. This
// models an order that crosses the spread and pays it; a resting limit order's fill probability is
// out of reach, not deferred.
//
// No fees anywhere in here. Fees are a swept parameter (OD-11) and enter at M7-T4; a fee constant
// in this file would be a bug.
#ifndef PERPCARRY_IMPACT_SIMULATOR_HPP
#define PERPCARRY_IMPACT_SIMULATOR_HPP

#include <cstddef>
#include <cstdint>

#include "perpcarry/order_book.hpp"

namespace perpcarry {

// Deliberately not `Side`. `Side::Bid` names a side of the book; `OrderSide::Buy` names what an
// order does -- and a buy consumes the *ask* side. Reusing one enum for both is how a sign error
// gets written that reads correctly at every call site.
enum class OrderSide : std::uint8_t { Buy, Sell };

// Levels the vendor reference (book_snapshot_25) actually constrains. This is NOT a limit on the
// walk -- it is a limit on what may be claimed about it. See D-021: capping the walk here would
// make large orders look cheaper than they are, which is the flattering direction to be wrong in.
inline constexpr std::size_t kValidatedDepth = 25;

struct Fill {
  double requested_quantity = 0.0;
  double filled_quantity = 0.0;

  double notional = 0.0;  // sum(price * quantity) over consumed levels

  // NaN, never 0.0, when nothing filled. A zero would be a valid-looking price and would average
  // into a calibration dataset without complaint; a NaN propagates loudly to whoever forgot to
  // check `filled_quantity` first.
  double average_price = 0.0;
  double worst_price = 0.0;  // last level touched -- the tail of the cost

  // NaN when the relevant side is empty, so a one-sided book cannot silently produce a reference
  // price out of nothing.
  double mid_at_entry = 0.0;
  double touch_at_entry = 0.0;  // best ask for a buy, best bid for a sell

  // Cost, signed so that positive is always worse for the trader: a buy that paid above the
  // reference and a sell that received below it both report positive.
  //
  // Both are reported because they answer different questions. Against the touch is the cost of
  // *size* alone -- what walking past the first level cost. Against the mid includes the
  // half-spread, which is what a round trip actually pays. M7 must not double-count the spread,
  // and M5 should not have to reconstruct either from the other.
  double slippage_vs_mid_bps = 0.0;
  double slippage_vs_touch_bps = 0.0;

  std::size_t levels_consumed = 0;

  bool exhausted_book = false;         // the side ran out before the order was filled
  bool beyond_validated_depth = false; // the walk passed kValidatedDepth (D-021)
  bool crossed_at_entry = false;       // best bid >= best ask when the order arrived
};

// Walks `book` and returns what the order filled at. The book is not modified: M5 simulates many
// sizes against the same instant.
//
// A crossed book is walked and flagged rather than refused. Measured on 0GUSDT 2026-06-01, 82,356
// of 1,299,113 updates leave the book crossed -- 6.3%, so a sampler lands there constantly, and a
// rule to discard those instants should be chosen from evidence in M5 rather than assumed here.
// Note that `slippage_vs_mid_bps` is against a mid that sits inside the spread's inversion when
// this flag is set, which is precisely why the flag travels with the number.
//
// Throws std::invalid_argument for a non-finite or non-positive quantity. Filling nothing is a
// result; being asked to fill nothing is a caller error.
Fill simulate_market_order(const OrderBook& book, OrderSide side, double quantity);

}  // namespace perpcarry

#endif  // PERPCARRY_IMPACT_SIMULATOR_HPP
