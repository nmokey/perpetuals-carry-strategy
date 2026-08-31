#include "perpcarry/impact_simulator.hpp"

#include <cmath>
#include <limits>
#include <span>
#include <stdexcept>
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

Fill simulate_market_order(const OrderBook& book, OrderSide side, double quantity) {
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

}  // namespace perpcarry
