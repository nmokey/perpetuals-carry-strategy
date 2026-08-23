#include "perpcarry/order_book.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <string>

namespace perpcarry {
namespace {

// Levels are stored best-first, so "better" differs by side: a higher bid is better, a
// lower ask is better. This one predicate fixes both the ordering and the binary search.
bool is_better(Side side, double lhs, double rhs) {
  return side == Side::Bid ? lhs > rhs : lhs < rhs;
}

void validate(double price, double quantity) {
  if (!std::isfinite(price) || price <= 0.0) {
    throw std::invalid_argument("order book price must be finite and positive, got " +
                                std::to_string(price));
  }
  if (!std::isfinite(quantity) || quantity < 0.0) {
    throw std::invalid_argument("order book quantity must be finite and non-negative, got " +
                                std::to_string(quantity));
  }
}

}  // namespace

OrderBook::OrderBook() {
  bids_.reserve(kInitialLevelCapacity);
  asks_.reserve(kInitialLevelCapacity);
}

std::vector<Level>& OrderBook::side_levels(Side side) {
  return side == Side::Bid ? bids_ : asks_;
}

const std::vector<Level>& OrderBook::side_levels(Side side) const {
  return side == Side::Bid ? bids_ : asks_;
}

void OrderBook::apply(Side side, double price, double quantity) {
  validate(price, quantity);
  std::vector<Level>& levels = side_levels(side);

  // First level not better than `price` -- so an existing level at exactly `price` lands
  // under `pos`, and a new one inserts here to keep the vector ordered.
  const auto pos = std::lower_bound(
      levels.begin(), levels.end(), price,
      [side](const Level& level, double target) { return is_better(side, level.price, target); });

  // Exact float equality is correct here and is the reason prices may stay `double`:
  // a price is only ever *compared*, never derived. Both the value stored and the value
  // matched against it are parsed from the same decimal text upstream, so they are the
  // same double. Arithmetic on prices happens in M4, on values read out of the book.
  const bool found = pos != levels.end() && pos->price == price;

  if (quantity == 0.0) {
    if (found) {
      levels.erase(pos);
    }
    return;
  }

  if (found) {
    pos->quantity = quantity;
  } else {
    levels.insert(pos, Level{price, quantity});
  }
}

void OrderBook::clear() {
  bids_.clear();
  asks_.clear();
}

std::optional<Level> OrderBook::best(Side side) const {
  const std::vector<Level>& levels = side_levels(side);
  if (levels.empty()) {
    return std::nullopt;
  }
  return levels.front();
}

std::optional<Level> OrderBook::best_bid() const { return best(Side::Bid); }

std::optional<Level> OrderBook::best_ask() const { return best(Side::Ask); }

bool OrderBook::is_crossed() const {
  if (bids_.empty() || asks_.empty()) {
    return false;
  }
  return bids_.front().price >= asks_.front().price;
}

std::size_t OrderBook::level_count(Side side) const { return side_levels(side).size(); }

std::span<const Level> OrderBook::levels(Side side) const { return side_levels(side); }

}  // namespace perpcarry
