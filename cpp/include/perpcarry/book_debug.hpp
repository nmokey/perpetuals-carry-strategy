// Human- and machine-readable renderings of book state. See
// docs/specs/M2/M2-T3-book-debug-serialization.md.
//
// M2-T2 answers "does the replayed book match the reference here"; a boolean cannot answer
// the only useful follow-up, which is "how". These three functions turn a BookDiff into
// something a person can read, and they are also the surface M4 will reach for when a
// simulated fill price looks wrong and the book is the first suspect.
//
// All three are pure: state in, text out. They open no files -- the core does no file I/O
// (D-012), and rendering raw book data to a path is exactly what the Tardis licence
// constrains (Clause 9.2(2)), so the choice of destination belongs to the caller.
#ifndef PERPCARRY_BOOK_DEBUG_HPP
#define PERPCARRY_BOOK_DEBUG_HPP

#include <cstddef>
#include <iosfwd>
#include <span>
#include <string>

#include "perpcarry/book_compare.hpp"
#include "perpcarry/order_book.hpp"

namespace perpcarry {

// Renders one price level's number the way every function here does: shortest round-trip
// via std::to_chars, with a ".0" appended when that yields an integer-looking string.
//
// The precision is a correctness property rather than a cosmetic one. A fixed "%.8f" would
// render 0.000012345678901 as 0.00001235 -- and a dump that rounds is a dump that can hide
// the very mismatch it was produced to explain. The ".0" is separate and purely cosmetic:
// it keeps 100.0 from printing as "100" and reading like an integer field.
//
// Locale-independent by construction, which std::ostream's operator<< is not.
std::string format_price(double value);

// side,level,price,quantity -- bids best-to-worst, then asks best-to-worst, `depth` levels
// per side at most. Same column vocabulary as the long-form book_snapshot corpus (D-014),
// so a dump loads into DuckDB or greps line by line with no translation.
//
// Note what is *not* claimed: the numbers are formatted for round-trip, not to match the
// exporter's own rendering byte for byte, so `diff` against a pyarrow-written reference
// export may show differences that are purely textual. Compare values, not lines.
void dump_csv(const OrderBook& book, std::ostream& out, std::size_t depth);

// The human form: asks worst-to-best above, spread line, bids best-to-worst below, with a
// cumulative-quantity column per side. Cumulative depth is here because it is the quantity
// M4 actually walks; a ladder without it hides the number the reader came for.
//
// The header always names the true level count against the rendered depth
// ("top 25 of 1013 bid / 1002 ask") so a truncated ladder is never read as a whole book.
std::string format_ladder(const OrderBook& book, std::size_t depth);

// The two ladders side by side, mismatched levels marked, matching levels left as context:
// a price mismatch at rank 7 is usually explained by what happened at rank 6.
//
// Returns the empty string when `diff` is empty -- "no differences" renders as nothing to
// read, not as a table of agreements.
//
// Takes both reference sides because BookDiff holds only the levels that *differ*, which
// is not enough to draw the context around them. It deliberately takes no ambiguity flag:
// whether an image's pairing was forced is a property of how the caller paired events to
// images, not of the levels, so that caveat is the caller's line to print above this one.
std::string format_diff(const BookDiff& diff, const OrderBook& replayed,
                        std::span<const Level> reference_bids,
                        std::span<const Level> reference_asks, std::size_t depth);

}  // namespace perpcarry

#endif  // PERPCARRY_BOOK_DEBUG_HPP
