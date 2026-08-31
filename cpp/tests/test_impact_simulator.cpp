// M4-T1 -- the static book-walk simulator.
// Spec: docs/specs/M4/M4-T1-static-book-walk.md, decision D-021.
//
// The design doc's criterion is "unit tests against hand-computed book-walk examples". Those are
// tests 1-3 and they are necessary; they are also nowhere near sufficient, because they check
// arithmetic on books someone chose. What a real day produces is crossed books (6.3% of updates on
// 0GUSDT 2026-06-01), sides thinner than the order, and walks past any depth a reference
// constrains. Those are the cases below that matter.

#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_floating_point.hpp>

#include <cmath>
#include <vector>

#include "perpcarry/impact_simulator.hpp"

using Catch::Matchers::WithinAbs;
using Catch::Matchers::WithinRel;
using perpcarry::Fill;
using perpcarry::kValidatedDepth;
using perpcarry::OrderBook;
using perpcarry::OrderSide;
using perpcarry::Side;
using perpcarry::simulate_market_order;

namespace {

// bid 99.5 x 6, 99.0 x 2.5   |   ask 100.5 x 4, 101.0 x 3, 102.0 x 10
// Mid is 100.0, so the half-spread is exactly 0.5 and slippage arithmetic stays checkable by hand.
OrderBook sample_book() {
  OrderBook book;
  book.apply(Side::Bid, 99.5, 6.0);
  book.apply(Side::Bid, 99.0, 2.5);
  book.apply(Side::Ask, 100.5, 4.0);
  book.apply(Side::Ask, 101.0, 3.0);
  book.apply(Side::Ask, 102.0, 10.0);
  return book;
}

OrderBook deep_ask_book(std::size_t levels) {
  OrderBook book;
  book.apply(Side::Bid, 99.0, 1.0);
  for (std::size_t i = 0; i < levels; ++i) {
    book.apply(Side::Ask, 100.0 + static_cast<double>(i) * 0.1, 1.0);
  }
  return book;
}

}  // namespace

TEST_CASE("a walk across whole levels is the size-weighted mean", "[impact]") {
  const OrderBook book = sample_book();

  // 4 @ 100.5 + 3 @ 101.0 = 402 + 303 = 705 over 7 units.
  const Fill fill = simulate_market_order(book, OrderSide::Buy, 7.0);

  REQUIRE(fill.filled_quantity == 7.0);
  REQUIRE(fill.notional == 705.0);
  REQUIRE_THAT(fill.average_price, WithinRel(705.0 / 7.0, 1e-15));
  REQUIRE(fill.levels_consumed == 2);
  REQUIRE(fill.worst_price == 101.0);
  REQUIRE_FALSE(fill.exhausted_book);
}

TEST_CASE("an order inside the best level fills entirely at that price", "[impact]") {
  const OrderBook book = sample_book();

  const Fill fill = simulate_market_order(book, OrderSide::Buy, 1.5);

  REQUIRE(fill.filled_quantity == 1.5);
  REQUIRE(fill.average_price == 100.5);
  REQUIRE(fill.levels_consumed == 1);
  REQUIRE(fill.worst_price == 100.5);
  REQUIRE_FALSE(fill.exhausted_book);
}

TEST_CASE("an order landing exactly on a level boundary consumes no extra level", "[impact]") {
  const OrderBook book = sample_book();

  // Exactly the best ask's 4 units: the classic off-by-one would touch 100.5 and 101.0.
  const Fill fill = simulate_market_order(book, OrderSide::Buy, 4.0);

  REQUIRE(fill.levels_consumed == 1);
  REQUIRE(fill.average_price == 100.5);
  REQUIRE(fill.worst_price == 100.5);
  REQUIRE_FALSE(fill.exhausted_book);
}

TEST_CASE("a buy consumes the asks and a sell consumes the bids", "[impact]") {
  const OrderBook book = sample_book();

  // Asserted by price rather than by reading back a side field, which would be the same mistake
  // twice if the mapping were wrong.
  const Fill buy = simulate_market_order(book, OrderSide::Buy, 1.0);
  const Fill sell = simulate_market_order(book, OrderSide::Sell, 1.0);

  REQUIRE(buy.average_price == 100.5);   // best ask
  REQUIRE(sell.average_price == 99.5);   // best bid
  REQUIRE(buy.touch_at_entry == 100.5);
  REQUIRE(sell.touch_at_entry == 99.5);
}

TEST_CASE("an order larger than the side fills partially and invents nothing", "[impact]") {
  const OrderBook book = sample_book();

  // The ask side holds 17 units in total.
  const Fill fill = simulate_market_order(book, OrderSide::Buy, 25.0);

  REQUIRE(fill.requested_quantity == 25.0);
  REQUIRE(fill.filled_quantity == 17.0);
  REQUIRE(fill.exhausted_book);
  REQUIRE(fill.levels_consumed == 3);
  // 4*100.5 + 3*101 + 10*102 = 402 + 303 + 1020
  REQUIRE(fill.notional == 1725.0);
  // The average must not be dragged toward the last price by liquidity that was never there.
  REQUIRE_THAT(fill.average_price, WithinRel(1725.0 / 17.0, 1e-15));
}

TEST_CASE("an empty side fills nothing and reports no price", "[impact]") {
  OrderBook book;
  book.apply(Side::Bid, 99.0, 5.0);  // bids only

  const Fill fill = simulate_market_order(book, OrderSide::Buy, 1.0);

  REQUIRE(fill.filled_quantity == 0.0);
  REQUIRE(fill.exhausted_book);
  REQUIRE(fill.levels_consumed == 0);
  // NaN rather than 0.0: a zero is a valid-looking price and would average into a calibration
  // dataset without complaint.
  REQUIRE(std::isnan(fill.average_price));
  REQUIRE(std::isnan(fill.worst_price));
  REQUIRE(std::isnan(fill.mid_at_entry));   // one-sided book has no mid
  REQUIRE(std::isnan(fill.touch_at_entry));
  REQUIRE(std::isnan(fill.slippage_vs_mid_bps));
  REQUIRE(std::isnan(fill.slippage_vs_touch_bps));
}

TEST_CASE("a crossed book is walked and flagged, not refused", "[impact]") {
  OrderBook book;
  book.apply(Side::Bid, 101.0, 5.0);
  book.apply(Side::Ask, 100.0, 5.0);
  REQUIRE(book.is_crossed());

  const Fill fill = simulate_market_order(book, OrderSide::Buy, 2.0);

  REQUIRE(fill.crossed_at_entry);
  REQUIRE(fill.filled_quantity == 2.0);
  REQUIRE(fill.average_price == 100.0);
  // The fill is real; the *mid* is the thing that is not meaningful here, which is why the flag
  // travels with the number instead of the sample being silently dropped.
  REQUIRE(fill.mid_at_entry == 100.5);

  const Fill uncrossed = simulate_market_order(sample_book(), OrderSide::Buy, 2.0);
  REQUIRE_FALSE(uncrossed.crossed_at_entry);
}

TEST_CASE("walk depth is reported, and flagged past the validated depth", "[impact]") {
  // 40 ask levels of 1 unit each, so the order size *is* the number of levels consumed.
  const OrderBook book = deep_ask_book(40);

  SECTION("inside the validated depth") {
    const Fill fill = simulate_market_order(book, OrderSide::Buy, 25.0);
    REQUIRE(fill.levels_consumed == kValidatedDepth);
    REQUIRE_FALSE(fill.beyond_validated_depth);
  }

  SECTION("one level past it") {
    const Fill fill = simulate_market_order(book, OrderSide::Buy, 26.0);
    REQUIRE(fill.levels_consumed == kValidatedDepth + 1);
    REQUIRE(fill.beyond_validated_depth);
  }

  SECTION("the walk is not capped at the validated depth (D-021)") {
    // Capping would report a cheaper fill than the book supports -- wrong in the flattering
    // direction, and it would bound the capacity answer by an artifact of the reference data.
    const Fill fill = simulate_market_order(book, OrderSide::Buy, 40.0);
    REQUIRE(fill.filled_quantity == 40.0);
    REQUIRE(fill.levels_consumed == 40);
    REQUIRE_FALSE(fill.exhausted_book);
    REQUIRE(fill.worst_price > 100.0 + 0.1 * static_cast<double>(kValidatedDepth));
  }
}

TEST_CASE("slippage is reported against both mid and touch", "[impact]") {
  const OrderBook book = sample_book();  // mid 100.0, best ask 100.5, best bid 99.5

  SECTION("a fill inside the best level costs nothing against the touch") {
    const Fill fill = simulate_market_order(book, OrderSide::Buy, 1.0);
    REQUIRE_THAT(fill.slippage_vs_touch_bps, WithinAbs(0.0, 1e-12));
    // The two differ by exactly the half-spread: 0.5 / 100.0 = 50 bps.
    REQUIRE_THAT(fill.slippage_vs_mid_bps, WithinRel(50.0, 1e-12));
  }

  SECTION("a sell is signed so that positive is still a cost") {
    const Fill fill = simulate_market_order(book, OrderSide::Sell, 1.0);
    REQUIRE_THAT(fill.slippage_vs_touch_bps, WithinAbs(0.0, 1e-12));
    REQUIRE_THAT(fill.slippage_vs_mid_bps, WithinRel(50.0, 1e-12));
  }

  SECTION("walking deeper costs more against both references") {
    const Fill shallow = simulate_market_order(book, OrderSide::Buy, 1.0);
    const Fill deep = simulate_market_order(book, OrderSide::Buy, 7.0);
    REQUIRE(deep.slippage_vs_touch_bps > shallow.slippage_vs_touch_bps);
    REQUIRE(deep.slippage_vs_mid_bps > shallow.slippage_vs_mid_bps);
  }
}

TEST_CASE("average price is non-improving in size, on both sides", "[impact]") {
  // A property rather than an example: this is what catches a sign error that every hand-computed
  // case happened to agree with.
  const OrderBook book = deep_ask_book(40);
  OrderBook bids;
  for (std::size_t i = 0; i < 40; ++i) {
    bids.apply(Side::Bid, 100.0 - static_cast<double>(i) * 0.1, 1.0);
  }
  bids.apply(Side::Ask, 101.0, 1.0);

  double previous_buy = 0.0;
  double previous_sell = 1e18;
  for (int size = 1; size <= 40; ++size) {
    const Fill buy = simulate_market_order(book, OrderSide::Buy, static_cast<double>(size));
    const Fill sell = simulate_market_order(bids, OrderSide::Sell, static_cast<double>(size));

    REQUIRE(buy.average_price >= previous_buy);    // a bigger buy never pays less on average
    REQUIRE(sell.average_price <= previous_sell);  // a bigger sell never receives more
    REQUIRE(buy.slippage_vs_touch_bps >= 0.0);     // never better than the price you started at
    REQUIRE(sell.slippage_vs_touch_bps >= 0.0);
    previous_buy = buy.average_price;
    previous_sell = sell.average_price;
  }
}

TEST_CASE("invalid quantities are rejected rather than filling nothing quietly", "[impact]") {
  const OrderBook book = sample_book();

  // Filling nothing is a result; being *asked* to fill nothing is a caller error, and returning an
  // empty fill would make a bug upstream look like an illiquid market.
  REQUIRE_THROWS_AS(simulate_market_order(book, OrderSide::Buy, 0.0), std::invalid_argument);
  REQUIRE_THROWS_AS(simulate_market_order(book, OrderSide::Buy, -1.0), std::invalid_argument);
  REQUIRE_THROWS_AS(simulate_market_order(book, OrderSide::Buy,
                                          std::numeric_limits<double>::quiet_NaN()),
                    std::invalid_argument);
  REQUIRE_THROWS_AS(simulate_market_order(book, OrderSide::Buy,
                                          std::numeric_limits<double>::infinity()),
                    std::invalid_argument);
}

TEST_CASE("simulating is deterministic and does not consume the book", "[impact]") {
  const OrderBook book = sample_book();

  const Fill first = simulate_market_order(book, OrderSide::Buy, 7.0);
  const Fill second = simulate_market_order(book, OrderSide::Buy, 7.0);

  // Bit-identical, and the second call saw the same book -- M5 simulates many sizes against one
  // instant, so a walk that consumed the book would silently make every later size cheaper.
  REQUIRE(first.average_price == second.average_price);
  REQUIRE(first.notional == second.notional);
  REQUIRE(first.filled_quantity == second.filled_quantity);
  REQUIRE(first.levels_consumed == second.levels_consumed);
  REQUIRE(book.level_count(Side::Ask) == 3);
  REQUIRE(book.best_ask()->quantity == 4.0);
}
