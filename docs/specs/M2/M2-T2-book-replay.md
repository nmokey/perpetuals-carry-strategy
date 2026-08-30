# M2-T2 — Snapshot + diff replay logic

**Milestone:** M2
**Status:** **Complete 2026-08-29.** `book_replayer.{hpp,cpp}`, `book_compare.{hpp,cpp}`,
`cpp/tools/replay_validate.*`, `python/perpcarry/tools/export_book.py`; 16 Catch2 tests + 10
pytest tests, 12/12 mutations caught. Both real-data runs pass — summaries in
`docs/validation/`. **The tolerance rule below was revised during the work (D-019):** the
unambiguous subset is empty on `BTCUSDT`, so the criterion now asserts on every image. The
original reasoning is kept as written, since the revision only makes sense against it.
**Depends on:** M2-T1; D-012 (batch input, no C++ file I/O), D-013 (ms timestamps), D-014
(long-form reference), D-018 (validation harness)
**Design doc:** Section 3.2, Section 4.2, Section 5 (M2)

## Goal

`BookReplayer` — drives an `OrderBook` through a day of `incremental_book_L2`, resetting on
snapshot blocks and applying diffs in order. This is the task that turns a data structure into
*the state of the market at an instant*, which is the input M4 needs and the thing M5's calibration
is ultimately a function of. It is also the only place where this project's book can be checked
against an outside party's: §3.2 has no `update_id`, so snapshot comparison is the **entire**
correctness argument for the book, not one check among several.

## Acceptance criteria

Copied verbatim from the design doc Section 5 table:

> Replayed state matches the vendor's independently-constructed `book_snapshot_25` for the same
> day, top 25 levels, within documented tolerance

### The tolerance, made concrete

"Within documented tolerance" is the part that has to be pinned down before any code is written,
because the obvious reading of it is unachievable and the second-obvious reading is dishonest.

**Measured on `0GUSDT` 2026-06-01, 2026-08-22:**

| Quantity | Value |
|---|---|
| Incremental rows / distinct millisecond timestamps | 1,299,113 / 414,207 |
| Timestamps non-decreasing in file order | yes |
| Reference images (each exactly 50 rows, 25 levels × 2 sides) | 277,590 |
| Images whose millisecond contains **no** incremental row | **0** |
| Images with no incremental row within ±10 ms | **0** |
| Incremental rows sharing an image's millisecond | mean 3.83, median 2, p99 28, max 1,452 |
| Images whose millisecond contains **exactly one** incremental row | **105,142 (37.9%)** |
| Images whose millisecond contains ≤2 | 62.5% |

Two consequences:

1. **There are no quiet comparison points.** The vendor emits an image on book change, so every
   image shares a millisecond with the diff that produced it. Any design that waits for a gap
   between events before comparing has nothing to compare — on the thinnest symbol in the corpus,
   whose median inter-event gap is 72 ms. This was worth measuring rather than assuming.
2. **The ambiguity is ours, not the vendor's.** Ingest truncates µs→ms (D-013), so when several
   diffs share a millisecond with an image, their order relative to that image is not recoverable
   from the corpus. It is recoverable from the vendor CSV at microsecond resolution — see Q3.

**So the tolerance is a partition, not an epsilon:**

- **Unambiguous set** — images whose millisecond holds exactly one incremental row. The pairing is
  forced, so equality is required to be **exact**: all 25 levels per side, `price` and `quantity`
  compared bitwise. Both sides are `float64` produced by the same vendor pipeline from the same
  decimal text; there is no arithmetic between them, so anything short of exact equality means the
  replay is wrong. 105,142 points on one thin day is not a thin sample.
- **Ambiguous set** — everything else. The mismatch rate is **reported, not asserted**. Asserting
  on it would be asserting on an artifact of our own normalisation, and an epsilon wide enough to
  absorb it would be wide enough to hide a real defect.

**The criterion is met when the unambiguous set has zero mismatches.** If a residual survives, it
gets characterised and documented — not converted into a tolerance. An epsilon introduced to make a
book comparison pass is the exact mechanism by which "calibrated from real data" quietly becomes
"calibrated from data that nearly matches real data".

> **Revised 2026-08-29 (D-019).** The paragraph above is wrong in one respect, and the measurement
> that broke it is worth keeping visible. On `BTCUSDT` 2026-06-01 the unambiguous set is **empty**
> — zero of 287,193 images, because at ~1.9 events per millisecond every image shares its
> millisecond with several events. A criterion evaluable on `0GUSDT` and vacuous on the symbol
> M2–M4 actually replays is not a criterion.
>
> **The rule is now: zero mismatches across all images**, with the unambiguous count still computed
> and reported as the part that needs no assumption. This is *stricter* than what is written above
> — it asserts on 459,641 images the original rule would only have counted — and it rests on one
> stated assumption: that the vendor emits an image only after applying the whole millisecond
> group. Evidence: 564,783 images across two symbols, zero counter-examples. Exact equality, with
> no epsilon, is unchanged.

### Expanded into checkable tests

CI-runnable, synthetic fixtures only (Tardis Clause 9.2(2), C9):

| # | Test | Where |
|---|---|---|
| 1 | Opening snapshot block builds initial state; the book is empty before it | `cpp/tests/test_book_replayer.cpp` |
| 2 | A batch whose first row is not `is_snapshot` is rejected with a message naming the missing initial state | same |
| 3 | Diffs after the opening block apply as diffs, not as a reset | same |
| 4 | A snapshot row following any diff **clears** the book, then accumulates the block | same |
| 5 | Consecutive snapshot rows within one block accumulate — one reset per block, not per row | same |
| 6 | Resync events are counted per *block*, not per row (a 1,400-row block is one event) | same |
| 7 | A resync block split across two `apply_batch` calls still counts as one event and resets once | same |
| 8 | `quantity == 0` inside a snapshot block is a no-op, matching the 13 such rows in BTC's real opening block | same |
| 9 | A batch whose timestamps decrease is rejected | same |
| 10 | A batch whose first timestamp precedes the previous batch's last is rejected | same |
| 11 | `Stats` counts (applied, resyncs, removals, crossed observations, last timestamp) match a hand-computed synthetic stream | same |
| 12 | Replaying one batch of N rows and N batches of 1 row give identical final state and identical `Stats` | same |
| 13 | Top-25 comparison against a synthetic reference: identical books compare clean | same |
| 14 | Each injected defect (dropped diff, applied-but-should-be-reset snapshot, sign-flipped removal) is caught by the comparison | same |
| 15 | The harness end to end on a synthetic events+reference pair with a defect injected at one known timestamp: it reports that timestamp and exits non-zero | `cpp/tests/test_replay_validate.cpp` |

Local, real-data, **not in CI** (D-018):

| # | Check | How |
|---|---|---|
| 16 | `0GUSDT` 2026-06-01: zero mismatches on the 105,142 unambiguous points | `perpcarry_replay_validate`; JSON summary committed |
| 17 | `BTCUSDT` 2026-06-01 (161,057,093 events, 2,309,043 images): same, once, with runtime recorded | same |

**Results, 2026-08-29** (`docs/validation/M2-T2-*.json`):

| | `0GUSDT` | `BTCUSDT` |
|---|---|---|
| Coverage | full day, 1,299,113 events | first 20,000,361 events (~12%) |
| Images compared | 277,590 | 287,193 |
| Unambiguous | 105,142 | **0** |
| Mismatches (unambiguous / ambiguous) | 0 / 0 | 0 / 0 |
| Resyncs | 13 | 1 |
| Crossed observations | 82,356 (6.3%) | 2,011,452 (10.1%) |
| Wall time | 2.3 s | 13.4 s |

The `0GUSDT` resync count of 13 independently reproduces `fetch_book.ingest`'s figure for the same
day, from a separate implementation in a different language — the closest thing available to a
second opinion on the sequencing rule.

**Why `BTCUSDT` is a 12% prefix and not the full day.** A full-day CSV export is ~15 GB against
20 GB free. `--max-events` takes a prefix, rounded up to a millisecond boundary — cutting mid-group
leaves the final image describing a book strictly ahead of the replayed one, which produced exactly
one guaranteed mismatch on the first attempt and looked precisely like a replay defect.

**Test 16/17 were also run inverted**, because a check that has never failed on real data is not
known to work on real data (C12). Deleting one top-of-book update from the real `0GUSDT` events
produced 10 mismatches, correctly categorised, at the expected timestamps. Deleting one *deep*
update produced none — see the limitation below.

Test 12 is the one that would catch the defect a reviewer should most suspect: state carried
incorrectly across batch boundaries. Batching is an artifact of D-012's boundary, and a replayer
whose answer depends on how the input was chunked is wrong in a way no single-batch test can see.

## Design

### Sequencing rules

- **Snapshot transition, not snapshot row.** `clear()` fires on the transition from a non-snapshot
  row into a snapshot row; rows within a block accumulate. This is exactly `fetch_book.ingest`'s
  `resync_events` rule (`prev_snapshot` initialised true so the opening block is not an event), and
  the two definitions must not drift — the rule is stated once here and both implementations cite
  this spec. Measured: 13 resync events on `0GUSDT` 2026-06-01 (18,396 rows) and 13 on `BTCUSDT`
  the same day.
- **File order is the sequence.** There is no `update_id` (§3.2, B-003), and ms timestamps tie
  freely — median 3.83 rows share a millisecond around an image. Row order as written by
  `fetch_book.ingest` is therefore load-bearing, and any reader that reorders rows silently
  corrupts the replay. Stated here because it is invisible in the schema.
- **Preconditions, checked rather than assumed** (C14): timestamps non-decreasing within and across
  batches, first batch opens with a snapshot. Both are cheap, both are verified true on real data,
  and a violation of either means the input pipeline is wrong in a way that otherwise produces a
  plausible book and no error.

### Interface

```cpp
class BookReplayer {
 public:
  struct Stats {
    std::int64_t applied = 0;       // rows consumed
    std::int64_t resyncs = 0;       // mid-stream snapshot blocks (excludes the opening one)
    std::int64_t removals = 0;      // quantity == 0 rows
    std::int64_t crossed = 0;       // updates after which best_bid >= best_ask
    std::int64_t last_timestamp = 0;
  };

  void apply(const BookUpdate& update);
  std::size_t apply_batch(std::span<const BookUpdate> batch);  // D-012: a batch, never a path

  const OrderBook& book() const;
  Stats stats() const;
};
```

`apply_batch` takes a span and no ownership: in M3-T1 that becomes a zero-copy view over a buffer
Python built, which is the whole point of putting the boundary at the batch level (Risk R4).

`Stats` exists so a replay is *characterised* rather than merely completed. A day that replays
without error but logs 400,000 crossed observations has told you something; a `void` return would
not have.

### Comparison

`compare_top_n(const OrderBook&, std::span<const Level> reference_bids, std::span<const Level>
reference_asks, std::size_t n)` returns a structured result: per side, per level, the categories
`price_mismatch`, `quantity_mismatch`, `missing_level` (replayed book is thinner than the
reference), `extra_level`. Structured rather than boolean because M2-T3 renders it, and because
"which level and in what way" is the difference between a debuggable failure and a re-run.

Fewer than 25 levels on a side is a `missing_level` mismatch, not a pass by omission — the
replayed book is ~1,000 deep, so a thin side means state was lost.

### Validation harness (D-018)

`python -m perpcarry.tools.export_book --symbol 0GUSDT --date 2026-06-01` reads the Parquet corpus
and writes two CSVs under `data/` (already gitignored): events in file order, and the long-form
reference images. `perpcarry_replay_validate` consumes them, replays, compares at every image, and
emits a human-readable report plus a JSON summary.

The tool has file I/O; `perpcarry_core` still has none and links no Arrow (D-012 unchanged). Built
under a new `PERPCARRY_BUILD_TOOLS` option, ON for standalone builds and forced OFF under `SKBUILD`
alongside the tests, so no wheel build acquires it.

Only the JSON summary is committed — counts and rates, aggregated and non-reconstructible, which is
what the licence permits (M1-T3's Licence section). The CSVs are corpus-shaped raw book rows and
are treated exactly as `data/` is.

## Data

**Input.** `data/book/symbol={SYMBOL}/date={DATE}/*.parquet` — §3.2 as written by `fetch_book`:
`exchange, timestamp, local_timestamp, latency_us, is_snapshot, side, price, quantity`, timestamps
in ms (D-013), `quantity == 0` meaning removal.

**Reference.** `data/book_snapshot/symbol={SYMBOL}/date={DATE}/*.parquet` — long form per D-014:
`exchange, timestamp, local_timestamp, latency_us, side, level, price, quantity`, one row per
level, empty trailing levels dropped. Grouping by `timestamp` reconstitutes an image; on `0GUSDT`
2026-06-01 every image is a full 50 rows, but the code reads the levels present rather than
assuming 25 — the same reasoning as `snapshot_depth()` (D-014).

**Output.** No corpus writes. A JSON summary per validated symbol-day, committed under
`docs/validation/M2-T2-{symbol}-{date}.json`: row and image counts, unambiguous/ambiguous split,
mismatch counts by category, replay `Stats`, wall time, and the git SHA it was produced at.

## Invariants this task must not break

**Determinism.** Replay is a pure fold over an ordered event sequence: same input, same final
state, byte for byte. Test 12 (batching-invariance) is the sharp form of this — determinism that
holds only for one chunking is not determinism.

**No look-ahead.** The replayer never reads beyond the update it is applying, so book state at time
*t* depends only on rows at or before *t*. Comparison inherits this: the state compared against an
image at *T* is built from rows up to *T* and nothing after. Test 14's "dropped diff" injection
fails loudly rather than being smoothed by later rows, which is the property that matters.

**Honest limitations.** Three get carried into M9 from here, all measured rather than estimated:

1. **Only the top 25 levels are validated.** A dropped update deep in the book replays wrongly and
   this harness passes — demonstrated, not hypothesised. By level count the check constrains ~2.5%
   of a 1000-level book, and M4 walks far deeper than that for large orders. On the watch list.
2. **The ambiguous-image assertion rests on an assumption** (D-019) about when the vendor emits an
   image. Well supported — 564,783 images, zero counter-examples — but an assumption, not a
   guarantee, and it is the reason the unambiguous count is still reported separately.
3. **D-018's C10 gap**: the real-data check is a dated local run, because the licence forbids CI
   ever seeing the input.

A fourth is worth noting but is *not* a limitation of this task: a dropped update self-heals at the
next update to that price, because L2 diffs carry absolute quantities rather than deltas. That
narrows the window in which any corruption is observable — including by this check.

## Out of scope

- Human-readable ladder rendering and the sampled-timestamp automated diff — **M2-T3**. This task
  owns the comparison *logic* and its verdict; T3 owns presentation and the sampling.
- Python access to the replayer — **M3-T1**. The harness is C++ precisely so this task does not
  depend on it.
- Threading the replayer behind a queue — **M3-T2**.
- Anything that walks the book to price an order — **M4**.

## Open questions

**Q1 — which days form the validation set?**
Recommendation: `0GUSDT` 2026-06-01 as the routine check (1.3M events, 105k unambiguous comparison
points, seconds to run), plus `BTCUSDT` 2026-06-01 once as the scale run (161M events, 2.3M images)
with its runtime recorded for M10's baseline. Both are already on disk. Adding 2026-07-01 and
2026-08-01 for `0GUSDT` costs nothing and guards against a day-specific fluke.

**Q2 — batch size for `apply_batch` in the harness?**
Recommendation: 1M rows, and report peak RSS in the summary. D-012 named batch-bounded memory as
its stated cost; the harness is the first thing that can measure it, so it should.

**Q3 — recover the ambiguous 62.1% by reading the vendor CSV at microsecond resolution?**
Recommendation: not now, and record why. It means a second read path that bypasses the corpus, so
the thing validated would no longer be the thing M4 consumes. The current split already yields
105k exact comparison points per thin day. Worth revisiting only if the unambiguous set comes back
clean *and* a reviewer wants coverage of the dense-update regime specifically — in which case the
honest framing is a separate microsecond-fidelity study, not a widened tolerance.

**Q4 — should `crossed` observations have a threshold that fails the run?**
Recommendation: no, count and report. Transient crossing is real in an aggregated feed, no
threshold can be justified before seeing the distribution, and a number in the summary is what lets
one be chosen later with evidence.
