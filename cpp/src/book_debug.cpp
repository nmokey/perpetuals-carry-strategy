#include "perpcarry/book_debug.hpp"

#include <algorithm>
#include <array>
#include <charconv>
#include <optional>
#include <ostream>
#include <string>
#include <vector>

namespace perpcarry {
namespace {

const char* side_name(Side side) { return side == Side::Bid ? "bid" : "ask"; }

const char* kind_name(DiffKind kind) {
  switch (kind) {
    case DiffKind::PriceMismatch:
      return "price";
    case DiffKind::QuantityMismatch:
      return "quantity";
    case DiffKind::MissingLevel:
      return "missing";
    case DiffKind::ExtraLevel:
      return "extra";
  }
  return "unknown";
}

// A cell that is absent rather than zero. Rendering a missing level as 0.0 would put a
// number where there is no level, and a reader comparing two ladders would take it for a
// real price of zero.
const char* kAbsent = "-";

// Right-aligns every column to the widest cell in it, header included, and trims the
// trailing whitespace a short last cell would otherwise leave. Widths come from the
// content, so a 0.000012345678901 book and a 108351.20 book both line up, and the result
// stays a pure function of the input.
std::string render_table(const std::vector<std::vector<std::string>>& rows) {
  if (rows.empty()) return {};

  std::vector<std::size_t> widths(rows.front().size(), 0);
  for (const std::vector<std::string>& row : rows) {
    for (std::size_t i = 0; i < row.size(); ++i) {
      widths[i] = std::max(widths[i], row[i].size());
    }
  }

  std::string out;
  for (const std::vector<std::string>& row : rows) {
    std::string line;
    for (std::size_t i = 0; i < row.size(); ++i) {
      if (i != 0) line += "  ";
      line.append(widths[i] - row[i].size(), ' ');
      line += row[i];
    }
    while (!line.empty() && line.back() == ' ') line.pop_back();
    out += line;
    out += '\n';
  }
  return out;
}

// Spread is arithmetic on prices, which is worth a word given that OrderBook keys on
// double. The invariant that permits double keys is that a price is never *derived* before
// being compared or looked up; this subtracts two values read back out of the book purely
// to display them, and feeds nothing back in. Same category as M4's book walk.
std::optional<double> spread_of(std::span<const Level> bids, std::span<const Level> asks) {
  if (bids.empty() || asks.empty()) return std::nullopt;
  return asks.front().price - bids.front().price;
}

std::string spread_text(std::span<const Level> bids, std::span<const Level> asks) {
  const std::optional<double> spread = spread_of(bids, asks);
  if (!spread.has_value()) return "n/a";
  std::string text = format_price(*spread);
  // Crossing is reported, never repaired (OrderBook::is_crossed) -- so it is labelled here
  // too. A negative number alone is easy to skim past.
  if (*spread <= 0.0) text += " CROSSED";
  return text;
}

std::string level_header(const OrderBook& book, std::size_t depth) {
  return "top " + std::to_string(depth) + " of " +
         std::to_string(book.level_count(Side::Bid)) + " bid / " +
         std::to_string(book.level_count(Side::Ask)) + " ask";
}

// Levels actually rendered for one side of a plain ladder.
std::size_t rendered_count(const OrderBook& book, Side side, std::size_t depth) {
  return std::min(depth, book.level_count(side));
}

const LevelDiff* find_diff(const BookDiff& diff, Side side, std::size_t rank) {
  for (const LevelDiff& level : diff.differences) {
    if (level.side == side && level.rank == rank) return &level;
  }
  return nullptr;
}

}  // namespace

std::string format_price(double value) {
  // 24 characters is the worst case for shortest round-trip of a double
  // ("-2.2250738585072014e-308"); 32 leaves room and keeps this off the heap.
  std::array<char, 32> buffer{};
  const std::to_chars_result result =
      std::to_chars(buffer.data(), buffer.data() + buffer.size(), value);
  std::string text(buffer.data(), result.ptr);

  // "100" is a correct shortest round-trip, but it reads as an integer field in a column of
  // prices. Appending ".0" changes no value -- it parses back to the identical double.
  const bool looks_integral =
      text.find_first_of(".eEnia") == std::string::npos;  // nan / inf carry n, a, i
  if (looks_integral) text += ".0";
  return text;
}

void dump_csv(const OrderBook& book, std::ostream& out, std::size_t depth) {
  out << "side,level,price,quantity\n";
  for (const Side side : {Side::Bid, Side::Ask}) {
    const std::span<const Level> levels = book.levels(side);
    const std::size_t limit = rendered_count(book, side, depth);
    for (std::size_t rank = 0; rank < limit; ++rank) {
      out << side_name(side) << ',' << std::to_string(rank) << ','
          << format_price(levels[rank].price) << ',' << format_price(levels[rank].quantity)
          << '\n';
    }
  }
}

std::string format_ladder(const OrderBook& book, std::size_t depth) {
  const std::span<const Level> bids = book.levels(Side::Bid);
  const std::span<const Level> asks = book.levels(Side::Ask);
  const std::size_t bid_rows = rendered_count(book, Side::Bid, depth);
  const std::size_t ask_rows = rendered_count(book, Side::Ask, depth);

  std::string out = "book: " + level_header(book, depth) + "\n";
  if (bid_rows == 0 && ask_rows == 0) {
    // An empty book is a state, not an error, and it has to be distinguishable from a
    // renderer that produced nothing at all.
    out += "(empty)\n";
    return out;
  }

  const std::vector<std::string> header = {"side", "level", "price", "qty", "cum"};

  // Cumulative runs outward from the touch on both sides, because that is the direction M4
  // walks a book: the quantity available by the time a marketable order reaches rank k.
  double cumulative = 0.0;
  std::vector<std::vector<std::string>> ask_rows_out;
  for (std::size_t rank = 0; rank < ask_rows; ++rank) {
    cumulative += asks[rank].quantity;
    ask_rows_out.push_back({"ask", std::to_string(rank), format_price(asks[rank].price),
                            format_price(asks[rank].quantity), format_price(cumulative)});
  }
  // Asks print worst-first so the best ask sits adjacent to the best bid at the centre.
  std::reverse(ask_rows_out.begin(), ask_rows_out.end());

  cumulative = 0.0;
  std::vector<std::vector<std::string>> bid_rows_out;
  for (std::size_t rank = 0; rank < bid_rows; ++rank) {
    cumulative += bids[rank].quantity;
    bid_rows_out.push_back({"bid", std::to_string(rank), format_price(bids[rank].price),
                            format_price(bids[rank].quantity), format_price(cumulative)});
  }

  // One table, split around the spread line, so both sides share column widths and the
  // prices line up across the centre.
  std::vector<std::vector<std::string>> all{header};
  all.insert(all.end(), ask_rows_out.begin(), ask_rows_out.end());
  all.insert(all.end(), bid_rows_out.begin(), bid_rows_out.end());
  const std::string table = render_table(all);

  // Split after the column header plus every ask row, so the spread line lands between the
  // two sides without either side being rendered as a separate table.
  std::size_t split = 0;
  for (std::size_t line = 0; line <= ask_rows_out.size(); ++line) {
    split = table.find('\n', split) + 1;
  }
  out += table.substr(0, split);
  out += "--- spread " + spread_text(bids, asks) + " ---\n";
  out += table.substr(split);
  return out;
}

std::string format_diff(const BookDiff& diff, const OrderBook& replayed,
                        std::span<const Level> reference_bids,
                        std::span<const Level> reference_asks, std::size_t depth) {
  if (diff.empty()) return {};

  const std::vector<std::string> header = {"side",            "level", "replayed_price",
                                           "replayed_qty",    "ref_price", "ref_qty",
                                           "note"};
  std::vector<std::vector<std::string>> ask_rows_out;
  std::vector<std::vector<std::string>> bid_rows_out;

  for (const Side side : {Side::Ask, Side::Bid}) {
    const std::span<const Level> mine = replayed.levels(side);
    const std::span<const Level> theirs = side == Side::Bid ? reference_bids : reference_asks;
    // Exactly the window compare_top_n examined -- not a re-derivation of it (C15).
    const std::size_t limit = compared_rank_count(mine.size(), theirs.size(), depth);

    std::vector<std::vector<std::string>>& rows = side == Side::Ask ? ask_rows_out : bid_rows_out;
    for (std::size_t rank = 0; rank < limit; ++rank) {
      const LevelDiff* mismatch = find_diff(diff, side, rank);
      rows.push_back({
          side_name(side),
          std::to_string(rank),
          rank < mine.size() ? format_price(mine[rank].price) : kAbsent,
          rank < mine.size() ? format_price(mine[rank].quantity) : kAbsent,
          rank < theirs.size() ? format_price(theirs[rank].price) : kAbsent,
          rank < theirs.size() ? format_price(theirs[rank].quantity) : kAbsent,
          mismatch != nullptr ? std::string("! ") + kind_name(mismatch->kind) : std::string(),
      });
    }
  }
  std::reverse(ask_rows_out.begin(), ask_rows_out.end());

  std::vector<std::vector<std::string>> all{header};
  all.insert(all.end(), ask_rows_out.begin(), ask_rows_out.end());
  all.insert(all.end(), bid_rows_out.begin(), bid_rows_out.end());
  const std::string table = render_table(all);

  std::size_t split = 0;
  for (std::size_t line = 0; line <= ask_rows_out.size(); ++line) {
    split = table.find('\n', split) + 1;
  }

  std::string out = "diff: " + level_header(replayed, depth) + ", " +
                    std::to_string(diff.size()) + " mismatching level(s)\n";
  out += table.substr(0, split);
  out += "--- spread " + spread_text(replayed.levels(Side::Bid), replayed.levels(Side::Ask)) +
         " | ref " + spread_text(reference_bids, reference_asks) + " ---\n";
  out += table.substr(split);
  return out;
}

}  // namespace perpcarry
