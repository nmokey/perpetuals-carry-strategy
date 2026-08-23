# M2-T3 — Book state debug serialization

**Milestone:** M2
**Status:** Draft
**Depends on:** M2-T2 (comparison logic and the validation harness); C13 (rendering is the property)
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
| 2 | Prices and quantities round-trip: parsing the dumped text yields the identical `double` | same |
| 3 | `format_ladder` of a known book equals an exact expected string — alignment, best bid/ask marker, spread line, cumulative column | same |
| 4 | Depth truncation: dumping top-25 of a 1,000-level book emits exactly 25 rows per side | same |
| 5 | A side thinner than the requested depth renders only the levels that exist — no blank or zero-filled rows | same |
| 6 | A crossed book renders with the crossed marker and a negative spread, not an abort | same |
| 7 | An empty book renders as an empty book, with a header, not as a crash or a blank string | same |
| 8 | `format_diff` of two identical books is empty | same |
| 9 | Each mismatch category (`price_mismatch`, `quantity_mismatch`, `missing_level`, `extra_level`) renders with the level marked and both values shown — four separate assertions on four separate mutations | same |
| 10 | The sampled-timestamp diff on a synthetic events+reference pair with a defect injected at one known timestamp: at least 3 timestamps are checked, the defective one is reported by timestamp, and the ladder for it appears in the output | `cpp/tests/test_replay_validate.cpp` |
| 11 | Same pair with no defect: 3+ timestamps checked, clean verdict, exit zero | same |

**Tests 1, 3 and 9 assert on freshly produced output, never on a committed golden file** (C13).
The book is constructed in the test, dumped, and compared to a literal string in the test. A stored
golden would pass whether or not the formatting code still ran — the exact trap M1-T5's first
formatting test fell into, where the artifact under test was already normalised.

## Design

**Two renderings, one comparison.** The comparison result comes from M2-T2 unchanged; this task
adds:

- `dump_csv(const OrderBook&, std::ostream&, std::size_t depth)` — `side,level,price,quantity`,
  bids then asks, best→worst. Deliberately the same vocabulary as the long-form `book_snapshot`
  corpus (D-014), so a dump can be diffed against a reference export with `diff`, loaded into
  DuckDB, or eyeballed, with no translation step.
- `format_ladder(const OrderBook&, std::size_t depth)` — the human form: asks descending above,
  bids descending below, best bid/ask adjacent at the centre, a spread line between them, and a
  cumulative-quantity column per side. Cumulative depth is included because it is the quantity M4
  actually walks; a ladder without it hides the number the reader came for.
- `format_diff(const BookDiff&, const OrderBook& replayed, std::span<const Level> reference…)` —
  the two ladders side by side, mismatched levels marked, matching levels dimmed to context. This
  is what `perpcarry_replay_validate` prints on failure.

**Number formatting is a correctness property, not cosmetics.** Prices are dumped with
`std::to_chars` shortest round-trip, so the text parses back to the identical double (test 2). A
`%.8f` would silently truncate `BTCUSDT`'s tick-aligned prices in some regimes and, worse, make a
real mismatch invisible in the output that exists to reveal it.

**Sampling for the automated diff.** The criterion asks for 3+ timestamps. The harness compares at
*every* unambiguous image already (M2-T2), so the sampled diff is not about coverage — it is about
producing inspectable output at a bounded number of points. Rule: report the first N (default 5)
distinct mismatching timestamps in full ladder form, then counts only. Otherwise a systematic
defect prints 105,142 ladders and the first one — the informative one — scrolls away.

When the run is clean, render 3 evenly spaced timestamps anyway (open, midday, close), so a passing
run still shows *something a human can check*, and "the diff ran" is distinguishable from "the diff
found nothing because it compared nothing" (C15's failure mode: a check that passes by not running).

**Licence: dump output is raw book data.** A ladder or CSV dump of a real symbol-day is exactly the
"per-level depth" the Tardis terms forbid redistributing (M1-T3 Licence, Clause 9.2(2)). So dumps
default to writing under `data/` (gitignored, and where the harness's CSVs already live), never to
`docs/` or the repo root, and never into a test fixture. The only committed artifact from a real
run stays the aggregated JSON summary from M2-T2. The C9 conftest fixture does not protect C++
tests, so this is a convention the tool's default path enforces rather than a rule to remember.

## Data

Input: an in-memory `OrderBook` plus, for the diff, a reference image (long-form levels, D-014).
Output: text on a stream. No corpus reads, no corpus writes, no dependency on storage.

## Invariants this task must not break

**Determinism.** Formatting is a pure function of book state and depth — no locale dependence (the
number formatting is `to_chars`, which is locale-independent by construction, unlike `ostream <<`),
no map iteration order, no timestamps in the output header beyond those passed in. A dump that
varies between runs would make the one artifact meant to explain a failure unreliable as evidence.

**Honest limitations.** The ladder shows the top N of a ~1,000-level book. Depth is always labelled
in the header (`top 25 of 1013 bid / 1002 ask`), so nobody reads a truncated ladder as a whole
book — the same reasoning that keeps `missing_level` a mismatch in M2-T2 rather than a pass.

## Out of scope

- The comparison semantics themselves — **M2-T2**.
- Dumping to Parquet or JSON. CSV plus the ladder covers machine diffing and human inspection;
  a third format is a maintenance cost with no reader.
- Rendering book state from Python — **M3-T1**, and probably never: the C++ dump is what the C++
  harness needs, and Python can already read the corpus directly.
- Visualisation (depth charts, book heatmaps) — **M9** reporting, if it earns its place there.

## Open questions

**Q1 — CSV or JSON for the machine-readable dump?**
Recommendation: CSV. It matches the long-form corpus vocabulary exactly (D-014), so a dump and a
reference export are diffable with no translation, and it is greppable line by line. JSON would
need a parser on both sides to do the same job.

**Q2 — colour / ANSI in the ladder?**
Recommendation: no. It is redundant with an explicit mismatch marker, it corrupts redirected output
(which is where a failing harness run will actually be read), and terminal detection is a branch
that would be untested on one of its two paths.

**Q3 — should `format_diff` show the surrounding context levels or only the mismatching ones?**
Recommendation: full top-N ladders with mismatches marked. A price mismatch at level 7 is usually
explained by what happened at level 6, and the whole point of the ladder over the CSV is that
context is visible without a second command.
