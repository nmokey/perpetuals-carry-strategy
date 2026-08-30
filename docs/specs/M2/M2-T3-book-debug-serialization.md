# M2-T3 — Book state debug serialization

**Milestone:** M2
**Status:** Complete (2026-08-29)
**Depends on:** M2-T2 (**complete 2026-08-29** — comparison logic and the validation harness); C13
(rendering is the property)
**Design doc:** Section 4.2, Section 5 (M2)

## Goal

Make a failed book comparison *readable*. M2-T2 answers "does the replayed book match the vendor's
at this timestamp"; when the answer is no, the only useful next question is "how", and a boolean
cannot answer it. This task produces the CSV dump, the human-readable ladder, and the sampled-
timestamp automated diff that turn a mismatch into a diagnosis. It is also the debugging surface
M4 will use when a simulated fill price looks wrong and the book is the first suspect.

## Acceptance criteria

Copied verbatim from the design doc Section 5 table:

> Automated diff against `book_snapshot_25` at 3+ sample timestamps, with human-readable output
> for inspection when it fails

**A sequencing note, surfaced rather than worked around (C4).** The doc lists T3 after T2, but
T2's harness needs a structured comparison to produce a verdict at all. The split that resolves it
without either task doing the other's work: **T2 owns the comparison and its verdict** (which
levels differ, in which category), **T3 owns rendering and sampling** (how a difference is shown,
and the automated 3+-timestamp check). T2 is therefore buildable without T3, and T3 adds no new
comparison semantics — it only renders `compare_top_n`'s existing result. Same shape as the M7-T3 /
M7-T4 wrinkle already on the watch list, resolved the same way: state the seam explicitly.

Expanded into checkable tests:

| # | Test | Where |
|---|---|---|
| 1 | `dump_csv` of a hand-built synthetic book equals an exact expected string — header, ordering, every field | `cpp/tests/test_book_dump.cpp` |
| 2 | Prices and quantities round-trip: parsing the dumped text yields the identical `double`, **on a value where the rejected `%.8f` would differ** (see below) | same |
| 3 | `format_ladder` of a known book equals an exact expected string — header, alignment, best bid/ask marker, spread line, cumulative column | same |
| 4 | Depth truncation: `dump_csv` and `format_ladder` at depth 25 of a 1,000-level book each emit exactly 25 rows per side | same |
| 5 | Truncation is labelled honestly: the ladder header of that same 1,000-level book reads the true per-side counts, not the depth (`top 25 of 1013 bid / 1002 ask`) | same |
| 6 | A side thinner than the requested depth renders only the levels that exist — no blank or zero-filled rows, in both `dump_csv` and `format_ladder` | same |
| 7 | A crossed book renders with the crossed marker and a negative spread, not an abort | same |
| 8 | An empty book renders as an empty book — `dump_csv` emits the header and no rows, `format_ladder` a header and an explicit empty marker; neither crashes nor returns a blank string | same |
| 9 | `format_diff` of two identical books is empty | same |
| 10 | Each mismatch category (`price_mismatch`, `quantity_mismatch`, `missing_level`, `extra_level`) renders with the level marked and both values shown — four separate assertions on four separate mutations | same |
| 11 | The sampled-timestamp diff on a synthetic events+reference pair with a defect injected at one known timestamp: at least 3 timestamps are checked, the defective one is reported by timestamp, and the ladder for it appears in the output | `cpp/tests/test_replay_validate.cpp` |
| 12 | Same pair with no defect: 3+ timestamps rendered, clean verdict, exit zero | same |
| 13 | A defect on an *ambiguous* image renders the ladder with the ambiguity caveat line; a defect on an unambiguous image renders without it | same |

**Tests 1, 3, 5 and 10 assert on freshly produced output, never on a committed golden file** (C13).
The book is constructed in the test, dumped, and compared to a literal string in the test. A stored
golden would pass whether or not the formatting code still ran — the exact trap M1-T5's first
formatting test fell into, where the artifact under test was already normalised.

**Test 2 must be aimed at the defect it exists to catch (C12).** A price like `108351.20`
round-trips through `%.8f` unharmed, so a round-trip test on realistic-looking values passes under
precisely the implementation this task rejects. Pin at least one value where the two differ — e.g.
a price of `0.000012345678901`, which `%.8f` renders as `0.00001235`. Delete the `to_chars` call
and the test must fail.

**Test 5 must be aimed the same way.** On a book with 25 levels a header reading `top 25 of 25 bid`
passes whether the count is the real level count or the depth argument echoed back. The 1,000-level
book is what makes the assertion mean something.

**Done when**, in addition: `perpcarry_replay_validate` has been run once against a real
`book_snapshot_25` symbol-day (the M2-T2 validation set) and its rendered output inspected by hand —
the criterion names `book_snapshot_25`, and CI can only ever see synthetic data (Licence, below).
Record that the run happened in `docs/progress.md`; the rendered ladders themselves are raw book
data and are not committed.

**Done 2026-08-29.** `0GUSDT` 2026-06-01, 277,590 images, verdict `pass` in 2.4s, three samples
rendered at 00:00:01.245, 12:00:00.034 and 23:59:59.598 — the midday one landing on the true
wall-clock midday, which is the property the anchoring rule exists for. The failure path was
exercised on the same real data by perturbing one reference quantity in a scratch copy: the defect
was located and rendered as a marked ladder, and a second, ambiguous mismatch produced by the
truncation carried the `AMBIGUOUS PAIRING` caveat — both caveat paths seen on real prices. No
output was written under `data/` or the repo.

## What M2-T2 actually built, and what is left for this task

The seam predicted below held, so this task starts from real interfaces rather than sketches:

- `compare_top_n(book, reference_bids, reference_asks, depth)` returns a `BookDiff` — a
  `std::vector<LevelDiff>`, each carrying `{side, rank, kind, replayed, reference}` with `kind` one
  of `PriceMismatch`, `QuantityMismatch`, `MissingLevel`, `ExtraLevel`. **All four categories are
  already produced and unit-tested.** This task renders that structure; it adds no comparison
  semantics.
- `perpcarry_replay_validate` already samples up to 5 mismatching timestamps (unambiguous and
  ambiguous separately) and prints a **plain one-line-per-level diagnostic** through
  `ValidationOptions::diagnostics` (`cpp/tools/replay_validate.cpp`). That printer is an explicit
  stopgap: it names the level and both values but shows no surrounding context, which is precisely
  what a ladder is for. **This task replaces it** — the sampling and bounding logic stays where it
  is.
- The harness compares at *every* image, not a sample. So the "3+ sample timestamps" criterion is
  about producing inspectable output at a bounded number of points, never about coverage.

**Two existing pieces this task must update, not just add alongside.**

1. `cpp/tests/test_replay_validate.cpp:166` ("the diagnostics stream names the level that differs")
   asserts on the stopgap's wording — `"bid rank 0"` — which a ladder will not emit. Replacing the
   printer breaks that test by construction. Migrate it to assert on the ladder's own markers rather
   than deleting it: it is the only test that the diagnostics stream is wired up at all.
2. The comment on `ValidationOptions::diagnostics` in `cpp/tools/replay_validate.hpp` says "the
   first mismatching image also gets its diff rendered here". The code has since sampled up to
   `max_sample_mismatches`. Correct it while replacing the printer it describes.

One thing the T2 work changed for this task: with the criterion now asserting on every image
(D-019), a failing run can report mismatches on *ambiguous* images too. A rendered mismatch must
therefore say which kind it is — an ambiguous one carries the extra caveat that its pairing was not
forced, and a reader who does not know that will chase the wrong thing first. **`BookDiff` carries
no ambiguity flag and should not grow one**: ambiguity is a property of the *pairing* the harness
performed, not of the levels that differ. So the caveat is the harness's line, printed above the
ladder, and `format_diff` stays a pure function of book state (test 13).

## Design

**Where this code lives.** The three formatting functions go in `perpcarry_core`, as
`cpp/include/perpcarry/book_debug.hpp` + `cpp/src/book_debug.cpp`. They take a stream or return a
string and **open no files** — the core does no file I/O (D-012), and this task does not change
that. The only caller that touches the filesystem is `perpcarry_replay_validate`, which already
owns its own paths (D-018).

**Two renderings, one comparison.** The comparison result comes from M2-T2 unchanged; this task
adds:

```cpp
// side,level,price,quantity -- bids then asks, best->worst.
void dump_csv(const OrderBook& book, std::ostream& out, std::size_t depth);

std::string format_ladder(const OrderBook& book, std::size_t depth);

std::string format_diff(const BookDiff& diff, const OrderBook& replayed,
                        std::span<const Level> reference_bids,
                        std::span<const Level> reference_asks, std::size_t depth);
```

- `dump_csv` deliberately uses the same vocabulary as the long-form `book_snapshot` corpus (D-014),
  so a dump loads into DuckDB or greps line by line with no translation step. **One thing the
  implementation walked back:** the draft also claimed a dump would be `diff`-able against a
  reference export. It is not, and cannot be — shortest round-trip and pyarrow's own number
  rendering disagree textually on values they agree on numerically, and round-trip is the property
  that has to win. Compare values, not lines; the header comment says so too.
- `format_ladder` is the human form: asks descending above, bids descending below, best bid/ask
  adjacent at the centre, a spread line between them, and a cumulative-quantity column per side.
  Cumulative depth is included because it is the quantity M4 actually walks; a ladder without it
  hides the number the reader came for.
- `format_diff` renders the two ladders side by side, mismatched levels marked, matching levels
  dimmed to context. It takes both reference sides because that is what `compare_top_n` compared
  against and what the right-hand ladder is built from; `BookDiff` alone holds only the levels that
  *differ*, which is not enough to draw context. This is what `perpcarry_replay_validate` prints on
  failure.

**Number formatting is a correctness property, not cosmetics.** Prices are dumped with
`std::to_chars` shortest round-trip, so the text parses back to the identical double (test 2). A
`%.8f` would silently truncate prices in some regimes and, worse, make a real mismatch invisible in
the output that exists to reveal it. One cosmetic addition on top: a result with no fractional text
gets `.0` appended, so `100.0` does not print as `100` in a column of prices. That changes no value
and is asserted separately from the round-trip.

**Sampling for the automated diff.** The criterion asks for 3+ timestamps. The harness compares at
*every* image already (M2-T2), so the sampled diff is not about coverage — it is about producing
inspectable output at a bounded number of points. Rule: report the first N (default 5) distinct
mismatching timestamps in full ladder form, then counts only. Otherwise a systematic defect prints
105,142 ladders and the first one — the informative one — scrolls away.

When the run is clean, render 3 timestamps anyway, so a passing run still shows *something a human
can check*, and "the diff ran" is distinguishable from "the diff found nothing because it compared
nothing" (C15's failure mode: a check that passes by not running).

**That sampling must be single-pass.** The harness streams both CSVs and never materialises them,
so the *last* image's timestamp is unknown until the run is over — "evenly spaced" cannot be
computed. Use wall-clock targets instead, anchored to the UTC day the first compared image falls
in: render the first image at or after `day_start` ("open") and at or after `day_start + 12h`
("midday").

For "close", **as built**, `ReferenceStream` gained a `has_more()` — exact one-image lookahead,
which it already holds internally — so the last image is recognised when it arrives. The draft
proposed keeping the most recent image's rendering in hand instead; that would have meant
formatting a ladder at every image, 2.3M of them on a BTCUSDT day, to keep one. Lookahead costs
nothing.

Anchoring to the *day* rather than to the first image matters and is easy to get wrong: a real
export opens a second or so after midnight (measured: `0GUSDT` 2026-06-01 opens at 00:00:01.245),
so a first-image anchor drifts the midday target past the midday image. Only compared images are
eligible — rendering an orphan would show a book that nothing checked. If the final image is an
orphan there is no close sample; the run then reports two rather than inventing a third.

**Licence: dump output is raw book data.** A ladder or CSV dump of a real symbol-day is exactly the
"per-level depth" the Tardis terms forbid redistributing (M1-T3 Licence, Clause 9.2(2)). Nothing in
this task writes a file: the ladders go to the harness's existing `diagnostics` stream, and the only
file the harness opens stays the aggregated JSON summary, which is also the only artifact of a real
run that may be committed. If a dump-to-file option is ever added it defaults under
`PERPCARRY_DATA_ROOT` (gitignored, where the harness's CSVs already live) — never `docs/`, never the
repo root, never a test fixture. The C9 conftest fixture does not protect C++ tests, so every
fixture in `test_book_dump.cpp` is hand-built synthetic data, as in `test_fetch_book.py`.

## Data

Input: an in-memory `OrderBook` plus, for the diff, a reference image (long-form levels, D-014).
Output: text on a stream or in a string. No corpus reads, no corpus writes, no dependency on
storage.

## Invariants this task must not break

**Determinism.** Formatting is a pure function of book state and depth — no locale dependence (the
number formatting is `to_chars`, which is locale-independent by construction, unlike `ostream <<`),
no map iteration order, no timestamps in the output header beyond those passed in. The cumulative
column sums floats, which is order-dependent in general but fixed here because the level order is;
do not "optimise" it into a different summation order. A dump that varies between runs would make
the one artifact meant to explain a failure unreliable as evidence.

**Honest limitations.** The ladder shows the top N of a ~1,000-level book. Depth is always labelled
in the header (`top 25 of 1013 bid / 1002 ask`), so nobody reads a truncated ladder as a whole
book — the same reasoning that keeps `missing_level` a mismatch in M2-T2 rather than a pass. Test 5
pins this on a book where the counts and the depth actually differ.

## Out of scope

- The comparison semantics themselves — **M2-T2**.
- Dumping to Parquet or JSON. CSV plus the ladder covers machine diffing and human inspection;
  a third format is a maintenance cost with no reader.
- A dump-to-file CLI. Nothing needs one yet: the harness's diagnostics stream is where a failing
  run is read, and shell redirection covers the rest.
- Rendering book state from Python — **M3-T1**, and probably never: the C++ dump is what the C++
  harness needs, and Python can already read the corpus directly.
- Visualisation (depth charts, book heatmaps) — **M9** reporting, if it earns its place there.

## Open questions

All three were adopted as recommended; kept here with their reasoning rather than deleted, since
the reasoning is what a later reader needs to reverse one.

**Q1 — CSV or JSON for the machine-readable dump? Adopted: CSV.**
Recommendation: CSV. It matches the long-form corpus vocabulary exactly (D-014), so a dump and a
reference export are diffable with no translation, and it is greppable line by line. JSON would
need a parser on both sides to do the same job.

**Q2 — colour / ANSI in the ladder? Adopted: no.**
Recommendation: no. It is redundant with an explicit mismatch marker, it corrupts redirected output
(which is where a failing harness run will actually be read), and terminal detection is a branch
that would be untested on one of its two paths.

**Q3 — surrounding context in `format_diff`, or only the mismatching levels? Adopted: full ladders.**
Recommendation: full top-N ladders with mismatches marked. A price mismatch at level 7 is usually
explained by what happened at level 6, and the whole point of the ladder over the CSV is that
context is visible without a second command.
