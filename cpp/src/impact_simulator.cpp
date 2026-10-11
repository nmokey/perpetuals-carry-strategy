#include "perpcarry/impact_simulator.hpp"

#include <cmath>
#include <limits>
#include <span>
#include <stdexcept>
#include <vector>
#include <string>

namespace perpcarry {
namespace {

constexpr double kNaN = std::numeric_limits<double>::quiet_NaN();

// A buy lifts the offers; a sell hits the bids. The single place this mapping is written.
Side consumed_side(OrderSide side) { return side == OrderSide::Buy ? Side::Ask : Side::Bid; }

// Cost in basis points, signed so positive is always worse for the trader. NaN reference in,
// NaN out -- a one-sided or empty book must not produce a slippage number.
double slippage_bps(OrderSide side, double average_price, double reference) {
  if (!std::isfinite(reference) || reference == 0.0 || !std::isfinite(average_price)) {
    return kNaN;
  }
  const double cost = side == OrderSide::Buy ? average_price - reference : reference - average_price;
  return cost / reference * 10000.0;
}

}  // namespace

namespace {

// The walk itself. `consumed` collects (price, remaining_quantity) for every level touched, so the
// caller can apply the depletion *after* the walk -- mutating during it would invalidate the span
// being iterated.
Fill walk(const OrderBook& book, OrderSide side, double quantity,
          std::vector<Level>* consumed) {
  if (!std::isfinite(quantity) || quantity <= 0.0) {
    throw std::invalid_argument("order quantity must be finite and positive, got " +
                                std::to_string(quantity));
  }

  Fill fill;
  fill.requested_quantity = quantity;
  fill.crossed_at_entry = book.is_crossed();

  const std::optional<Level> best_bid = book.best_bid();
  const std::optional<Level> best_ask = book.best_ask();
  fill.mid_at_entry = (best_bid.has_value() && best_ask.has_value())
                          ? (best_bid->price + best_ask->price) / 2.0
                          : kNaN;

  const std::optional<Level>& touch = side == OrderSide::Buy ? best_ask : best_bid;
  fill.touch_at_entry = touch.has_value() ? touch->price : kNaN;

  // The zero-copy span M2-T1 wrote for exactly this caller: M5 walks it once per simulated order,
  // so a copy here would be the allocation that decides the sweep's runtime.
  const std::span<const Level> levels = book.levels(consumed_side(side));

  double remaining = quantity;
  for (const Level& level : levels) {
    if (remaining <= 0.0) break;
    const double taken = remaining < level.quantity ? remaining : level.quantity;
    fill.notional += taken * level.price;
    fill.filled_quantity += taken;
    fill.worst_price = level.price;
    ++fill.levels_consumed;
    remaining -= taken;
    if (consumed != nullptr) consumed->push_back(Level{level.price, level.quantity - taken});
  }

  // Strictly greater: an order that exactly empties the side was filled, not starved.
  fill.exhausted_book = remaining > 0.0;
  fill.beyond_validated_depth = fill.levels_consumed > kValidatedDepth;

  if (fill.filled_quantity > 0.0) {
    fill.average_price = fill.notional / fill.filled_quantity;
  } else {
    fill.average_price = kNaN;
    fill.worst_price = kNaN;
  }

  fill.slippage_vs_mid_bps = slippage_bps(side, fill.average_price, fill.mid_at_entry);
  fill.slippage_vs_touch_bps = slippage_bps(side, fill.average_price, fill.touch_at_entry);
  return fill;
}

}  // namespace

Fill simulate_market_order(const OrderBook& book, OrderSide side, double quantity) {
  return walk(book, side, quantity, nullptr);
}

Fill execute_market_order(OrderBook& book, OrderSide side, double quantity) {
  std::vector<Level> consumed;
  const Fill fill = walk(book, side, quantity, &consumed);
  // Applied after the walk: a quantity of 0 removes the level, which is exactly OrderBook::apply's
  // existing contract, so no new removal path is introduced here.
  for (const Level& level : consumed) {
    book.apply(consumed_side(side), level.price, level.quantity);
  }
  return fill;
}

namespace {

// Child sizes from the schedule. The last slice takes whatever is left rather than its own
// computed share: dividing by a weight sum loses or invents a sliver of the parent order, and a
// capacity study that silently trades 0.9999 of what it claims is wrong in the flattering
// direction.
std::vector<double> slice_quantities(double total, const SliceSchedule& schedule) {
  const std::size_t n = schedule.slices;
  std::vector<double> weights = schedule.weights;
  if (weights.empty()) weights.assign(n, 1.0);

  double weight_sum = 0.0;
  for (const double w : weights) weight_sum += w;

  std::vector<double> sizes(n, 0.0);
  double assigned = 0.0;
  for (std::size_t i = 0; i + 1 < n; ++i) {
    sizes[i] = total * weights[i] / weight_sum;
    assigned += sizes[i];
  }
  sizes[n - 1] = total - assigned;
  return sizes;
}

void validate_schedule(double total_quantity, const SliceSchedule& schedule) {
  if (!std::isfinite(total_quantity) || total_quantity <= 0.0) {
    throw std::invalid_argument("order quantity must be finite and positive, got " +
                                std::to_string(total_quantity));
  }
  if (schedule.slices == 0) {
    throw std::invalid_argument("a schedule must have at least one slice");
  }
  if (schedule.duration_ms < 0) {
    throw std::invalid_argument("schedule duration must not be negative, got " +
                                std::to_string(schedule.duration_ms));
  }
  if (schedule.weights.empty()) return;

  if (schedule.weights.size() != schedule.slices) {
    throw std::invalid_argument("schedule has " + std::to_string(schedule.slices) +
                                " slices but " + std::to_string(schedule.weights.size()) +
                                " weights");
  }
  double weight_sum = 0.0;
  for (const double w : schedule.weights) {
    if (!std::isfinite(w) || w < 0.0) {
      throw std::invalid_argument("schedule weights must be finite and non-negative");
    }
    weight_sum += w;
  }
  if (weight_sum <= 0.0) {
    throw std::invalid_argument("schedule weights must not sum to zero");
  }
}

}  // namespace

SlicedFill simulate_sliced_execution(std::span<const BookUpdate> updates, OrderSide side,
                                     double total_quantity, const SliceSchedule& schedule) {
  return simulate_sliced_execution_from_state(BookReplayer{}, updates, side, total_quantity, schedule);
}

SlicedFill simulate_sliced_execution_from_state(const BookReplayer& initial,
                                                std::span<const BookUpdate> updates,
                                                OrderSide side, double total_quantity,
                                                const SliceSchedule& schedule) {
  validate_schedule(total_quantity, schedule);
  if (initial.stats().applied > 0 && initial.stats().last_timestamp > schedule.start_timestamp) {
    throw std::invalid_argument("initial replay state is later than sliced execution entry");
  }

  SlicedFill result;
  result.parent.requested_quantity = total_quantity;
  result.slices.reserve(schedule.slices);

  const std::vector<double> sizes = slice_quantities(total_quantity, schedule);
  BookReplayer replayer = initial;
  std::size_t cursor = 0;
  const std::int64_t n = static_cast<std::int64_t>(schedule.slices);

  for (std::size_t i = 0; i < schedule.slices; ++i) {
    // Integer arithmetic on the grid: slice 0 lands exactly on `start_timestamp`, and with
    // duration 0 every slice lands there, which is what makes a one-slice zero-duration schedule
    // identical to a static walk.
    const std::int64_t slice_time =
        schedule.start_timestamp +
        schedule.duration_ms * static_cast<std::int64_t>(i) / n;

    // Everything at or before this instant, and nothing after it. This single line is the
    // no-look-ahead guarantee.
    while (cursor < updates.size() && updates[cursor].timestamp <= slice_time) {
      replayer.apply(updates[cursor]);
      ++cursor;
    }

    if (sizes[i] <= 0.0) continue;  // a zero weight is a legitimate "skip this slot"
    // Consumes: the parent order's own footprint must persist between slices, or
    // splitting it would make it cheaper for free (D-023).
    const Fill fill = execute_market_order(replayer.mutable_book(), side, sizes[i]);
    result.slices.push_back(fill);

    if (fill.exhausted_book) ++result.slices_exhausted;
    if (fill.beyond_validated_depth) ++result.slices_beyond_validated_depth;
    if (fill.crossed_at_entry) ++result.slices_crossed;

    result.parent.notional += fill.notional;
    result.parent.filled_quantity += fill.filled_quantity;
    result.parent.levels_consumed += fill.levels_consumed;

    if (result.slices.size() == 1) {
      // Arrival references, taken at the first slice that actually executes -- a leading zero
      // weight is a skipped slot, not the start of the order.
      result.parent.mid_at_entry = fill.mid_at_entry;
      result.parent.touch_at_entry = fill.touch_at_entry;
      result.parent.crossed_at_entry = fill.crossed_at_entry;
      result.parent.worst_price = fill.worst_price;
    } else if (std::isfinite(fill.worst_price)) {
      const bool worse = side == OrderSide::Buy ? fill.worst_price > result.parent.worst_price
                                                : fill.worst_price < result.parent.worst_price;
      if (worse || !std::isfinite(result.parent.worst_price)) result.parent.worst_price = fill.worst_price;
    }
  }

  result.parent.exhausted_book = result.slices_exhausted > 0;
  result.parent.beyond_validated_depth = result.slices_beyond_validated_depth > 0;
  result.completed = result.slices_exhausted == 0;

  if (result.parent.filled_quantity > 0.0) {
    result.parent.average_price = result.parent.notional / result.parent.filled_quantity;
  } else {
    result.parent.average_price = kNaN;
    result.parent.worst_price = kNaN;
  }
  result.parent.slippage_vs_mid_bps =
      slippage_bps(side, result.parent.average_price, result.parent.mid_at_entry);
  result.parent.slippage_vs_touch_bps =
      slippage_bps(side, result.parent.average_price, result.parent.touch_at_entry);
  return result;
}

}  // namespace perpcarry
