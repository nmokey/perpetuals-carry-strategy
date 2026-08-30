// M2-T3 -- book state debug serialization.
// Spec: docs/specs/M2/M2-T3-book-debug-serialization.md.
//
// Every expected string below is compared against output produced *in this test*, from a
// book built two lines above it. None of it is read from a committed golden file, which is
// the trap M1-T5's first formatting test fell into: a stored artifact already holds the
// normalised text, so the assertion passes whether or not the code that normalises it still
// runs (C13).
//
// Every fixture here is synthetic. Vendor book rows may not enter the repository at all
// (Tardis Clause 9.2(2)), and the C9 conftest fixture that enforces that on the Python side
// does not see C++ tests.

#include <catch2/catch_test_macros.hpp>

#include <charconv>
#include <cstddef>
#include <sstream>
#include <string>
#include <system_error>
#include <vector>

#include "perpcarry/book_debug.hpp"

using perpcarry::BookDiff;
using perpcarry::compare_top_n;
using perpcarry::dump_csv;
using perpcarry::format_diff;
using perpcarry::format_ladder;
using perpcarry::format_price;
using perpcarry::Level;
using perpcarry::OrderBook;
using perpcarry::Side;

namespace {

// The book every exact-string test renders. Three bids, two asks, uncrossed.
OrderBook sample_book() {
  OrderBook book;
  book.apply(Side::Bid, 100.0, 4.0);
  book.apply(Side::Bid, 99.5, 6.0);
  book.apply(Side::Bid, 99.0, 2.5);
  book.apply(Side::Ask, 101.0, 7.0);
  book.apply(Side::Ask, 102.0, 8.0);
  return book;
}

std::string dump(const OrderBook& book, std::size_t depth) {
  std::ostringstream out;
  dump_csv(book, out, depth);
  return out.str();
}

// Rows of one side in a CSV dump: lines beginning "bid," or "ask,".
std::size_t csv_rows(const std::string& text, const std::string& side) {
  const std::string prefix = side + ",";
  std::istringstream in(text);
  std::string line;
  std::size_t count = 0;
  while (std::getline(in, line)) {
    if (line.rfind(prefix, 0) == 0) ++count;
  }
  return count;
}

// Rows of one side in a ladder: the cells are right-aligned, so the side is the first
// whitespace-separated token.
std::size_t ladder_rows(const std::string& text, const std::string& side) {
  std::istringstream in(text);
  std::string line;
  std::size_t count = 0;
  while (std::getline(in, line)) {
    std::istringstream fields(line);
    std::string token;
    fields >> token;
    if (token == side) ++count;
  }
  return count;
}

double parse(const std::string& text) {
  double value = 0.0;
  const auto result = std::from_chars(text.data(), text.data() + text.size(), value);
  REQUIRE(result.ec == std::errc());
  REQUIRE(result.ptr == text.data() + text.size());
  return value;
}

// Every price and quantity cell of a CSV dump, in order.
std::vector<std::string> csv_numbers(const std::string& text) {
  std::istringstream in(text);
  std::string line;
  std::vector<std::string> out;
  std::getline(in, line);  // header
  while (std::getline(in, line)) {
    const std::size_t second = line.find(',', line.find(',') + 1);
    const std::size_t third = line.find(',', second + 1);
    out.push_back(line.substr(second + 1, third - second - 1));
    out.push_back(line.substr(third + 1));
  }
  return out;
}

// A book deep enough that the rendered depth and the true level count differ. Without that
// gap a header reading "top 25 of 25 bid" passes whether it reports the real count or just
// echoes the depth argument back.
OrderBook deep_book(std::size_t bid_levels, std::size_t ask_levels) {
  OrderBook book;
  for (std::size_t i = 0; i < bid_levels; ++i) {
    book.apply(Side::Bid, 1000.0 - static_cast<double>(i) * 0.1, 1.0 + static_cast<double>(i));
  }
  for (std::size_t i = 0; i < ask_levels; ++i) {
    book.apply(Side::Ask, 1000.5 + static_cast<double>(i) * 0.1, 2.0 + static_cast<double>(i));
  }
  return book;
}

}  // namespace

TEST_CASE("dump_csv renders the whole book exactly", "[book_dump]") {
  const OrderBook book = sample_book();

  REQUIRE(dump(book, 3) ==
          "side,level,price,quantity\n"
          "bid,0,100.0,4.0\n"
          "bid,1,99.5,6.0\n"
          "bid,2,99.0,2.5\n"
          "ask,0,101.0,7.0\n"
          "ask,1,102.0,8.0\n");
}

TEST_CASE("dumped numbers parse back to the identical double", "[book_dump]") {
  // Chosen so the rejected fixed-precision rendering would be visibly wrong: "%.8f" turns
  // 0.000012345678901 into 0.00001235 and 12345678.901234567 into 12345678.90123457, both
  // of which parse back to a *different* double. A test built on prices like 100.0 would
  // pass under exactly the implementation this task rejects (C12).
  const double small = 0.000012345678901;
  const double large = 12345678.901234567;
  const double awkward = 0.1 + 0.2;  // 0.30000000000000004, not 0.3

  OrderBook book;
  book.apply(Side::Bid, small, awkward);
  book.apply(Side::Ask, large, 1e-9);

  const std::string text = dump(book, 25);
  const std::vector<std::string> numbers = csv_numbers(text);
  REQUIRE(numbers.size() == 4);

  REQUIRE(parse(numbers[0]) == small);
  REQUIRE(parse(numbers[1]) == awkward);
  REQUIRE(parse(numbers[2]) == large);
  REQUIRE(parse(numbers[3]) == 1e-9);

  // And the rendering really is the shortest round-trip one, not a fixed-decimal form that
  // happened to survive these particular values.
  REQUIRE(numbers[0] == "1.2345678901e-05");
  REQUIRE(numbers[1] == "0.30000000000000004");
}

TEST_CASE("format_price appends .0 only where the value has no fractional text",
          "[book_dump]") {
  REQUIRE(format_price(100.0) == "100.0");
  REQUIRE(format_price(99.5) == "99.5");
  REQUIRE(format_price(0.0) == "0.0");
  // The suffix is cosmetic and must never change the value.
  REQUIRE(parse(format_price(100.0)) == 100.0);
}

TEST_CASE("format_ladder renders the whole book exactly", "[book_dump]") {
  const OrderBook book = sample_book();

  REQUIRE(format_ladder(book, 3) ==
          "book: top 3 of 3 bid / 2 ask\n"
          "side  level  price  qty   cum\n"
          " ask      1  102.0  8.0  15.0\n"
          " ask      0  101.0  7.0   7.0\n"
          "--- spread 1.0 ---\n"
          " bid      0  100.0  4.0   4.0\n"
          " bid      1   99.5  6.0  10.0\n"
          " bid      2   99.0  2.5  12.5\n");
}

TEST_CASE("depth truncates both renderings to exactly the requested rows", "[book_dump]") {
  const OrderBook book = deep_book(1013, 1002);

  const std::string csv = dump(book, 25);
  REQUIRE(csv_rows(csv, "bid") == 25);
  REQUIRE(csv_rows(csv, "ask") == 25);

  const std::string ladder = format_ladder(book, 25);
  REQUIRE(ladder_rows(ladder, "bid") == 25);
  REQUIRE(ladder_rows(ladder, "ask") == 25);
}

TEST_CASE("the ladder header names the true depth, not the rendered one", "[book_dump]") {
  const OrderBook book = deep_book(1013, 1002);

  REQUIRE(format_ladder(book, 25).rfind("book: top 25 of 1013 bid / 1002 ask\n", 0) == 0);
}

TEST_CASE("a side thinner than the depth renders only the levels that exist", "[book_dump]") {
  OrderBook book;
  book.apply(Side::Bid, 100.0, 4.0);
  book.apply(Side::Ask, 101.0, 7.0);
  book.apply(Side::Ask, 102.0, 8.0);

  const std::string csv = dump(book, 25);
  REQUIRE(csv_rows(csv, "bid") == 1);
  REQUIRE(csv_rows(csv, "ask") == 2);

  const std::string ladder = format_ladder(book, 25);
  REQUIRE(ladder_rows(ladder, "bid") == 1);
  REQUIRE(ladder_rows(ladder, "ask") == 2);
  // No padding row standing in for the bid level that does not exist -- neither blank nor
  // zero-filled. Rank 1 must simply not be rendered on that side.
  REQUIRE(ladder.find(" bid      1") == std::string::npos);
}

TEST_CASE("a crossed book renders as crossed rather than aborting", "[book_dump]") {
  OrderBook book;
  book.apply(Side::Bid, 101.0, 1.0);
  book.apply(Side::Ask, 100.0, 2.0);
  REQUIRE(book.is_crossed());

  const std::string ladder = format_ladder(book, 5);
  REQUIRE(ladder.find("--- spread -1.0 CROSSED ---\n") != std::string::npos);

  // A *locked* book -- best bid exactly equal to best ask -- is crossed too: OrderBook's
  // predicate is `>=`, not `>`. With only the inverted case above, the renderer's own
  // threshold could be `< 0.0` and nothing would notice, because 101/100 satisfies both.
  // The boundary is where the two rules part company, so the test has to stand on it (C16).
  OrderBook locked;
  locked.apply(Side::Bid, 100.0, 1.0);
  locked.apply(Side::Ask, 100.0, 2.0);
  REQUIRE(locked.is_crossed());
  REQUIRE(format_ladder(locked, 5).find("--- spread 0.0 CROSSED ---\n") != std::string::npos);
}

TEST_CASE("an empty book renders as an empty book", "[book_dump]") {
  const OrderBook book;

  // A header and an explicit marker: "the book was empty" has to be distinguishable from
  // "the renderer produced nothing".
  REQUIRE(format_ladder(book, 25) ==
          "book: top 25 of 0 bid / 0 ask\n"
          "(empty)\n");
  REQUIRE(dump(book, 25) == "side,level,price,quantity\n");
}

TEST_CASE("format_diff of two identical books is empty", "[book_dump]") {
  const OrderBook book = sample_book();
  const std::vector<Level> bids = {{100.0, 4.0}, {99.5, 6.0}, {99.0, 2.5}};
  const std::vector<Level> asks = {{101.0, 7.0}, {102.0, 8.0}};

  const BookDiff diff = compare_top_n(book, bids, asks, 3);
  REQUIRE(diff.empty());
  REQUIRE(format_diff(diff, book, bids, asks, 3).empty());
}

TEST_CASE("every mismatch category renders the level and both values", "[book_dump]") {
  SECTION("price_mismatch") {
    const OrderBook book = sample_book();
    const std::vector<Level> bids = {{100.25, 4.0}, {99.5, 6.0}, {99.0, 2.5}};
    const std::vector<Level> asks = {{101.0, 7.0}, {102.0, 8.0}};

    const std::string text = format_diff(compare_top_n(book, bids, asks, 3), book, bids, asks, 3);
    REQUIRE(text.find(" bid      0  ") != std::string::npos);
    REQUIRE(text.find("! price") != std::string::npos);
    REQUIRE(text.find("100.0") != std::string::npos);   // replayed
    REQUIRE(text.find("100.25") != std::string::npos);  // reference
  }

  SECTION("quantity_mismatch") {
    const OrderBook book = sample_book();
    const std::vector<Level> bids = {{100.0, 4.5}, {99.5, 6.0}, {99.0, 2.5}};
    const std::vector<Level> asks = {{101.0, 7.0}, {102.0, 8.0}};

    const std::string text = format_diff(compare_top_n(book, bids, asks, 3), book, bids, asks, 3);
    REQUIRE(text.find("! quantity") != std::string::npos);
    REQUIRE(text.find("4.0") != std::string::npos);
    REQUIRE(text.find("4.5") != std::string::npos);
  }

  SECTION("missing_level -- the reference has a rank the replayed book lost") {
    OrderBook book;
    book.apply(Side::Bid, 100.0, 4.0);
    book.apply(Side::Ask, 101.0, 7.0);
    const std::vector<Level> bids = {{100.0, 4.0}, {99.5, 6.0}};
    const std::vector<Level> asks = {{101.0, 7.0}};

    const std::string text = format_diff(compare_top_n(book, bids, asks, 5), book, bids, asks, 5);
    REQUIRE(text.find("! missing") != std::string::npos);
    // The absent side reads as absent, not as a level priced at zero.
    REQUIRE(text.find(" bid      1               -             -       99.5      6.0  ! missing") !=
            std::string::npos);
  }

  SECTION("extra_level -- the replayed book has a rank the reference denies") {
    OrderBook book;
    book.apply(Side::Bid, 100.0, 4.0);
    book.apply(Side::Bid, 99.5, 6.0);
    book.apply(Side::Ask, 101.0, 7.0);
    const std::vector<Level> bids = {{100.0, 4.0}};
    const std::vector<Level> asks = {{101.0, 7.0}};

    const std::string text = format_diff(compare_top_n(book, bids, asks, 5), book, bids, asks, 5);
    REQUIRE(text.find("! extra") != std::string::npos);
    REQUIRE(text.find(" bid      1            99.5           6.0          -        -  ! extra") !=
            std::string::npos);
  }
}
