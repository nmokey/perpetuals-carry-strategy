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
#include <span>
#include <vector>

#include "perpcarry/book_replayer.hpp"
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

// The same walk, but it *consumes* what it took: levels fully eaten are removed and a partially
// eaten level is reduced. Returns the identical Fill.
//
// This exists because splitting an order must not make it cheaper by relabelling. Four slices of
// 5 units at one instant against a book that never depletes fill at the same average as one slice
// of 5 -- so a 20-unit parent would cost less than a 20-unit single order for no reason but the
// label. Consuming makes the two agree, which is both internally consistent and the conservative
// direction.
//
// **The stated approximation (D-023).** A later vendor update at a touched price carries an
// absolute quantity, so it overwrites whatever this left behind. Our hypothetical footprint
// therefore decays as the real book refreshes -- a crude impact-decay model, but one taken from
// the data rather than assumed, and the mechanism that makes spreading an order over time actually
// cheaper in M4-T2.
Fill execute_market_order(OrderBook& book, OrderSide side, double quantity);

// ---------------------------------------------------------------------------------------------
// M4-T2 -- time-sliced execution. See docs/specs/M4/M4-T2-sliced-execution.md.
// ---------------------------------------------------------------------------------------------

// A schedule, not a policy. TWAP and VWAP differ only in the weights, so the caller supplies them
// and the volume-profile question -- which needs trades aligned to the book -- stays out of the
// core and in M4-T3/M5 where the corpus lives.
struct SliceSchedule {
  std::int64_t start_timestamp = 0;  // ms, matching the book feed (D-013)
  std::int64_t duration_ms = 0;      // 0 puts every slice at `start_timestamp`
  std::size_t slices = 1;

  // Empty means equal weights (TWAP). Otherwise one weight per slice; they are normalised, so
  // relative magnitude is all that matters.
  std::vector<double> weights;
};

struct SlicedFill {
  // Aggregated over the children. Its reference prices are taken at the *first* slice, so
  // `slippage_vs_mid_bps` is arrival-price shortfall: what the whole order cost against the market
  // as it stood when execution began.
  //
  // `levels_consumed` is the sum across slices, not a maximum -- it is the total depth this parent
  // order ate through, which is the quantity a cost attribution wants.
  Fill parent;

  std::vector<Fill> slices;  // in execution order, so a parent fill can be attributed

  std::size_t slices_exhausted = 0;
  std::size_t slices_beyond_validated_depth = 0;
  std::size_t slices_crossed = 0;

  bool completed = false;  // every slice filled its full requested size
};

// Replays `updates` and executes `total_quantity` across the schedule, advancing the book between
// slices. `updates` must begin with a snapshot block, as BookReplayer requires.
//
// **No look-ahead, structurally.** The replayer is advanced only to each slice's timestamp before
// that slice is simulated, so updates after it have not been applied and cannot influence the fill.
// This is the most natural place in the whole project for look-ahead to enter -- one loop written
// in the wrong order and every slice fills against a book that already knows what happens next --
// which is why the containment is here rather than at each call site.
//
// Throws std::invalid_argument for a non-positive quantity, zero slices, a negative duration, or a
// weight vector that is the wrong length, non-finite, negative, or sums to zero.
SlicedFill simulate_sliced_execution(std::span<const BookUpdate> updates, OrderSide side,
                                     double total_quantity, const SliceSchedule& schedule);

// Calibration already replayed to entry. Copy that state, including snapshot-block state,
// rather than replaying the whole day's prefix for every size. Future updates must follow
// the initial state; the caller's replayer is never mutated.
SlicedFill simulate_sliced_execution_from_state(const BookReplayer& initial,
                                                std::span<const BookUpdate> future,
                                                OrderSide side, double total_quantity,
                                                const SliceSchedule& schedule);

}  // namespace perpcarry

#endif  // PERPCARRY_IMPACT_SIMULATOR_HPP
