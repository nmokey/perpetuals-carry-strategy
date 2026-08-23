// M2-T1 -- core price-level data structure.
// Spec: docs/specs/M2/M2-T1-order-book-core.md
//
// The criterion is test 10: agreement with an independent implementation over a randomised
// stream. The rest exist so that when it fails, the failure has a name.

#include <catch2/catch_test_macros.hpp>

#include <cstddef>
#include <cstdint>
#include <functional>
#include <limits>
#include <map>
#include <random>
#include <span>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include "perpcarry/order_book.hpp"

using perpcarry::Level;
using perpcarry::OrderBook;
using perpcarry::Side;

namespace {

// The independent reference: a deliberately naive node-based book. Structurally different
// from the sorted-vector implementation, so the two fail differently -- which is the whole
// value of the comparison.
class ReferenceBook {
 public:
  void apply(Side side, double price, double quantity) {
    if (side == Side::Bid) {
      update(bids_, price, quantity);
    } else {
      update(asks_, price, quantity);
    }
  }

  std::vector<Level> levels(Side side) const {
    std::vector<Level> out;
    if (side == Side::Bid) {
      for (const auto& [price, quantity] : bids_) out.push_back(Level{price, quantity});
    } else {
      for (const auto& [price, quantity] : asks_) out.push_back(Level{price, quantity});
    }
    return out;
  }

 private:
  template <typename Map>
  static void update(Map& book, double price, double quantity) {
    if (quantity == 0.0) {
      book.erase(price);
    } else {
      book[price] = quantity;
    }
  }

  std::map<double, double, std::greater<double>> bids_;  // best (highest) first
  std::map<double, double> asks_;                        // best (lowest) first
};

// Empty when the two agree. Compared with `==` and no tolerance: both hold values that
// were only ever copied, never computed, so anything short of exact equality is a defect.
std::string compare(const OrderBook& book, const ReferenceBook& reference) {
  for (const Side side : {Side::Bid, Side::Ask}) {
    const std::span<const Level> actual = book.levels(side);
    const std::vector<Level> expected = reference.levels(side);
    const char* name = side == Side::Bid ? "bid" : "ask";
    if (actual.size() != expected.size()) {
      std::ostringstream out;
      out << name << " level count " << actual.size() << " != " << expected.size();
      return out.str();
    }
    for (std::size_t i = 0; i < expected.size(); ++i) {
      if (actual[i].price != expected[i].price || actual[i].quantity != expected[i].quantity) {
        std::ostringstream out;
        out << name << " level " << i << ": got (" << actual[i].price << ", "
            << actual[i].quantity << ") want (" << expected[i].price << ", "
            << expected[i].quantity << ")";
        return out.str();
      }
    }
  }
  return {};
}

// A fixed grid of prices, computed once so that the book and the oracle are handed the
// identical double rather than two values that happen to print the same.
const std::vector<double>& price_grid() {
  static const std::vector<double> grid = [] {
    std::vector<double> prices;
    prices.reserve(400);
    for (int i = 0; i < 400; ++i) {
      prices.push_back(73000.0 + static_cast<double>(i) * 0.1);
    }
    return prices;
  }();
  return grid;
}

struct Operation {
  Side side;
  double price;
  double quantity;
};

// `rng() % n` rather than std::uniform_int_distribution: distributions are not portable
// across standard library implementations, and CI runs libc++ and libstdc++. Keeping the
// stream identical everywhere means a CI failure reproduces locally on the same seed.
std::vector<Operation> make_stream(std::uint32_t seed, std::size_t count) {
  const std::vector<double>& prices = price_grid();
  std::mt19937 rng(seed);
  std::vector<Operation> ops;
  ops.reserve(count);
  for (std::size_t i = 0; i < count; ++i) {
    const Side side = (rng() % 2) == 0 ? Side::Bid : Side::Ask;
    const double price = prices[rng() % prices.size()];
    // A quarter of operations are removals -- real days run ~11% (17.3M of 161M rows on
    // BTCUSDT 2026-06-01), and over-weighting them here exercises the erase path and the
    // remove-an-absent-level no-op far more often than a proportional mix would.
    const double quantity =
        (rng() % 4) == 0 ? 0.0 : 1.0 + static_cast<double>(rng() % 10000) * 0.001;
    ops.push_back(Operation{side, price, quantity});
  }
  return ops;
}

OrderBook replay(const std::vector<Operation>& ops) {
  OrderBook book;
  for (const Operation& op : ops) {
    book.apply(op.side, op.price, op.quantity);
  }
  return book;
}

bool same_state(const OrderBook& lhs, const OrderBook& rhs) {
  for (const Side side : {Side::Bid, Side::Ask}) {
    const std::span<const Level> a = lhs.levels(side);
    const std::span<const Level> b = rhs.levels(side);
    if (a.size() != b.size()) return false;
    for (std::size_t i = 0; i < a.size(); ++i) {
      if (a[i].price != b[i].price || a[i].quantity != b[i].quantity) return false;
    }
  }
  return true;
}

}  // namespace

TEST_CASE("an empty book has no best bid and no best ask", "[order_book]") {
  const OrderBook book;

  REQUIRE_FALSE(book.best_bid().has_value());
  REQUIRE_FALSE(book.best_ask().has_value());
  REQUIRE(book.level_count(Side::Bid) == 0);
  REQUIRE(book.level_count(Side::Ask) == 0);
  REQUIRE_FALSE(book.is_crossed());
}

TEST_CASE("a better price moves top of book and a worse price does not", "[order_book]") {
  OrderBook book;
  book.apply(Side::Bid, 100.0, 5.0);
  book.apply(Side::Ask, 101.0, 7.0);

  SECTION("a higher bid becomes the best bid") {
    book.apply(Side::Bid, 100.5, 2.0);
    REQUIRE(book.best_bid()->price == 100.5);
    REQUIRE(book.best_bid()->quantity == 2.0);
  }

  SECTION("a lower bid does not") {
    book.apply(Side::Bid, 99.5, 2.0);
    REQUIRE(book.best_bid()->price == 100.0);
    REQUIRE(book.best_bid()->quantity == 5.0);
  }

  SECTION("a lower ask becomes the best ask") {
    book.apply(Side::Ask, 100.5, 3.0);
    REQUIRE(book.best_ask()->price == 100.5);
    REQUIRE(book.best_ask()->quantity == 3.0);
  }

  SECTION("a higher ask does not") {
    book.apply(Side::Ask, 102.0, 3.0);
    REQUIRE(book.best_ask()->price == 101.0);
    REQUIRE(book.best_ask()->quantity == 7.0);
  }
}

TEST_CASE("a deep level insert leaves top of book untouched", "[order_book]") {
  OrderBook book;
  for (int i = 0; i < 600; ++i) {
    book.apply(Side::Bid, 100.0 - static_cast<double>(i) * 0.1, 1.0 + static_cast<double>(i));
    book.apply(Side::Ask, 101.0 + static_cast<double>(i) * 0.1, 2.0 + static_cast<double>(i));
  }
  const Level best_bid = *book.best_bid();
  const Level best_ask = *book.best_ask();

  // Level ~500 down each side: deeper than the 25 the vendor reference carries, and the
  // region a top-of-book-only implementation would get wrong without ever failing a
  // spread check.
  book.apply(Side::Bid, 50.05, 42.0);
  book.apply(Side::Ask, 150.05, 43.0);

  REQUIRE(book.best_bid()->price == best_bid.price);
  REQUIRE(book.best_bid()->quantity == best_bid.quantity);
  REQUIRE(book.best_ask()->price == best_ask.price);
  REQUIRE(book.best_ask()->quantity == best_ask.quantity);
  REQUIRE(book.level_count(Side::Bid) == 601);
  REQUIRE(book.level_count(Side::Ask) == 601);
}

TEST_CASE("quantity zero removes the level", "[order_book]") {
  OrderBook book;
  book.apply(Side::Bid, 100.0, 5.0);
  book.apply(Side::Bid, 99.0, 6.0);

  book.apply(Side::Bid, 100.0, 0.0);

  REQUIRE(book.level_count(Side::Bid) == 1);
  REQUIRE(book.best_bid()->price == 99.0);
  REQUIRE(book.best_bid()->quantity == 6.0);
}

TEST_CASE("removing a level that is not in the book is a no-op", "[order_book]") {
  // Not hypothetical: BTCUSDT 2026-06-01's opening *snapshot* block carries 13
  // zero-quantity rows, so a book that rejects this cannot ingest a real day.
  OrderBook book;
  book.apply(Side::Bid, 100.0, 5.0);

  REQUIRE_NOTHROW(book.apply(Side::Bid, 98.0, 0.0));
  REQUIRE_NOTHROW(book.apply(Side::Ask, 105.0, 0.0));

  REQUIRE(book.level_count(Side::Bid) == 1);
  REQUIRE(book.level_count(Side::Ask) == 0);
  REQUIRE(book.best_bid()->price == 100.0);
  REQUIRE(book.best_bid()->quantity == 5.0);
}

TEST_CASE("a removed price can be re-added at the correct rank", "[order_book]") {
  OrderBook book;
  book.apply(Side::Bid, 100.0, 1.0);
  book.apply(Side::Bid, 99.0, 2.0);
  book.apply(Side::Bid, 98.0, 3.0);

  book.apply(Side::Bid, 99.0, 0.0);
  book.apply(Side::Bid, 99.0, 9.0);

  const std::span<const Level> bids = book.levels(Side::Bid);
  REQUIRE(bids.size() == 3);
  REQUIRE(bids[0].price == 100.0);
  REQUIRE(bids[1].price == 99.0);
  REQUIRE(bids[1].quantity == 9.0);
  REQUIRE(bids[2].price == 98.0);
}

TEST_CASE("an update at an existing price replaces it in place", "[order_book]") {
  OrderBook book;
  book.apply(Side::Ask, 101.0, 1.0);
  book.apply(Side::Ask, 102.0, 2.0);

  book.apply(Side::Ask, 101.0, 7.5);

  const std::span<const Level> asks = book.levels(Side::Ask);
  REQUIRE(asks.size() == 2);
  REQUIRE(asks[0].price == 101.0);
  REQUIRE(asks[0].quantity == 7.5);
  REQUIRE(asks[1].price == 102.0);
}

TEST_CASE("levels are ordered best to worst on both sides", "[order_book]") {
  OrderBook book;
  // Inserted out of order on purpose: the ordering must be a property of the structure,
  // not of the order the caller happened to use.
  for (const double price : {99.0, 100.0, 97.0, 98.0}) {
    book.apply(Side::Bid, price, price);
  }
  for (const double price : {103.0, 101.0, 104.0, 102.0}) {
    book.apply(Side::Ask, price, price);
  }

  const std::span<const Level> bids = book.levels(Side::Bid);
  REQUIRE(bids.size() == 4);
  REQUIRE(bids[0].price == 100.0);
  REQUIRE(bids[1].price == 99.0);
  REQUIRE(bids[2].price == 98.0);
  REQUIRE(bids[3].price == 97.0);

  const std::span<const Level> asks = book.levels(Side::Ask);
  REQUIRE(asks.size() == 4);
  REQUIRE(asks[0].price == 101.0);
  REQUIRE(asks[1].price == 102.0);
  REQUIRE(asks[2].price == 103.0);
  REQUIRE(asks[3].price == 104.0);
}

TEST_CASE("clear empties both sides", "[order_book]") {
  OrderBook book;
  book.apply(Side::Bid, 100.0, 1.0);
  book.apply(Side::Bid, 99.0, 1.0);
  book.apply(Side::Ask, 101.0, 1.0);

  book.clear();

  REQUIRE(book.level_count(Side::Bid) == 0);
  REQUIRE(book.level_count(Side::Ask) == 0);
  REQUIRE_FALSE(book.best_bid().has_value());
  REQUIRE_FALSE(book.best_ask().has_value());

  book.apply(Side::Bid, 50.0, 2.0);
  REQUIRE(book.level_count(Side::Bid) == 1);
  REQUIRE(book.best_bid()->price == 50.0);
}

TEST_CASE("the book matches an independent reference over a randomised stream",
          "[order_book][differential]") {
  constexpr std::size_t kOperations = 100000;
  const std::vector<Operation> ops = make_stream(20260822U, kOperations);

  OrderBook book;
  ReferenceBook reference;
  std::size_t agreed = 0;

  for (std::size_t i = 0; i < ops.size(); ++i) {
    book.apply(ops[i].side, ops[i].price, ops[i].quantity);
    reference.apply(ops[i].side, ops[i].price, ops[i].quantity);

    const std::string difference = compare(book, reference);
    if (!difference.empty()) {
      INFO("diverged at operation " << i << ": " << difference);
      REQUIRE(difference.empty());
    }
    ++agreed;
  }

  // Both sides are compared in full after every single operation, so this counts
  // agreements, not iterations -- a loop that silently stopped comparing would fail here.
  REQUIRE(agreed == kOperations);
  REQUIRE(book.level_count(Side::Bid) > 0);
  REQUIRE(book.level_count(Side::Ask) > 0);
}

TEST_CASE("a price that is not exactly representable round-trips", "[order_book]") {
  // 0.4191 is 0GUSDT's best bid at the open of 2026-06-01 and is not exactly
  // representable in binary. It stays safe because a price is only ever compared, never
  // derived -- this pins that property rather than trusting it.
  OrderBook book;
  book.apply(Side::Bid, 0.4191, 1200.0);
  REQUIRE(book.level_count(Side::Bid) == 1);
  REQUIRE(book.best_bid()->price == 0.4191);

  book.apply(Side::Bid, 0.4191, 0.0);
  REQUIRE(book.level_count(Side::Bid) == 0);
}

TEST_CASE("a crossed book is reported, not repaired", "[order_book]") {
  OrderBook book;
  book.apply(Side::Bid, 100.0, 1.0);
  book.apply(Side::Ask, 101.0, 1.0);
  REQUIRE_FALSE(book.is_crossed());

  book.apply(Side::Bid, 101.5, 1.0);

  REQUIRE(book.is_crossed());
  // Both sides survive intact: nothing was trimmed to make the spread positive.
  REQUIRE(book.best_bid()->price == 101.5);
  REQUIRE(book.best_ask()->price == 101.0);
  REQUIRE(book.level_count(Side::Bid) == 2);
  REQUIRE(book.level_count(Side::Ask) == 1);

  SECTION("a locked book counts as crossed") {
    OrderBook locked;
    locked.apply(Side::Bid, 100.0, 1.0);
    locked.apply(Side::Ask, 100.0, 1.0);
    REQUIRE(locked.is_crossed());
  }

  SECTION("one empty side is not crossed") {
    OrderBook one_sided;
    one_sided.apply(Side::Bid, 100.0, 1.0);
    REQUIRE_FALSE(one_sided.is_crossed());
  }
}

TEST_CASE("invalid prices and quantities are rejected", "[order_book]") {
  OrderBook book;
  const double infinity = std::numeric_limits<double>::infinity();
  const double nan = std::numeric_limits<double>::quiet_NaN();

  REQUIRE_THROWS_AS(book.apply(Side::Bid, nan, 1.0), std::invalid_argument);
  REQUIRE_THROWS_AS(book.apply(Side::Bid, infinity, 1.0), std::invalid_argument);
  REQUIRE_THROWS_AS(book.apply(Side::Bid, 0.0, 1.0), std::invalid_argument);
  REQUIRE_THROWS_AS(book.apply(Side::Bid, -1.0, 1.0), std::invalid_argument);
  REQUIRE_THROWS_AS(book.apply(Side::Bid, 100.0, nan), std::invalid_argument);
  REQUIRE_THROWS_AS(book.apply(Side::Bid, 100.0, infinity), std::invalid_argument);
  REQUIRE_THROWS_AS(book.apply(Side::Bid, 100.0, -1.0), std::invalid_argument);

  // A rejected update leaves no trace.
  REQUIRE(book.level_count(Side::Bid) == 0);
}

TEST_CASE("the same stream replayed twice gives the same state", "[order_book]") {
  const std::vector<Operation> ops = make_stream(20260822U, 20000);

  const OrderBook first = replay(ops);
  const OrderBook second = replay(ops);

  REQUIRE(same_state(first, second));
  REQUIRE(first.level_count(Side::Bid) > 0);

  // A different seed must produce a different state, or the check above would pass on a
  // book that ignored its input entirely.
  const OrderBook other = replay(make_stream(1U, 20000));
  REQUIRE_FALSE(same_state(first, other));
}
