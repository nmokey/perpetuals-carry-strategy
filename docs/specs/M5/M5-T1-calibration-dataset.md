# M5-T1 — Calibration dataset generation

**Milestone:** M5
**Status:** Draft
**Depends on:** M4-T3 (complete 2026-08-30). No open design decision gates this task.
**Design doc:** Section 4.5, Section 5 (M5)

## Goal

Sweep (size, time, symbol) through the M4 simulator and write the per-fill rows that M5-T2 fits.
This is the task that turns a simulator into data. Everything downstream — the impact coefficients,
the entry threshold, the capacity curve — is a function of this dataset, so its coverage bounds what
the project can honestly claim more tightly than any modelling choice does.

**Nothing has been kept yet.** M4's probe simulated 1,554 static fills and 480 sliced runs and
retained *aggregates* — rates and means. There is currently no row-level dataset anywhere in the
project. That is this task.

## Acceptance criteria

Copied verbatim from the design doc Section 5 table:

> Deterministic given fixed seed; output Parquet dataset

Expanded into checkable tests:

| # | Test | Where |
|---|---|---|
| 1 | The same configuration run twice produces a byte-identical Parquet file | `tests/models/test_calibration_dataset.py` |
| 2 | The row count is exactly `instants × sizes × schedules`, so a silently dropped sample is visible | same |
| 3 | Every row carries the fields M5-T2 needs to fit *and* to caveat: size, both slippage measures, `levels_consumed`, `beyond_validated_depth`, `crossed_at_entry`, `exhausted_book` | same |
| 4 | **No look-ahead:** static fills are unchanged by perturbing/truncating events after entry; sliced fills are unchanged by perturbing/truncating events after their final slice, and each slice uses only events available by that slice's time | same |
| 5 | Sizes are generated log-spaced across a configured range, not from a hard-coded list, and the endpoints appear exactly | same |
| 6 | Size is recorded in base units **and** as %ADV and %depth, with the ADV window ending strictly before the sampled day | same |
| 7 | A sampled instant on a crossed book is written with the flag set, not silently skipped | same |
| 8 | Re-running over a day already present overwrites that partition rather than appending duplicates | same |
| 9 | The generator refuses a symbol-day with no book partition rather than emitting an empty dataset | same |
| 10 | Missing or quality-rejected days in the configured strictly prior ADV window cause an explicit failure rather than an average of only available days | same |

Test 1 is the criterion. Test 4 is the one that protects the result: this generator replays a book
and samples from it, which is the same shape as M4-T2 and the same place look-ahead enters.

## What this task must not paper over: the data ceiling

**2026-10-08 correction:** the table below describes historical book/trades overlap, not verified
calibration eligibility. Consult `blockers.md` for the later reported pull and unresolved quality
gap; verify complete prior ADV windows before counting usable days. The current checkout has no
corpus available to check.

**Historical corpus snapshot, 2026-08-30:**

| symbol | trades | book days | usable (book **and** trades) |
|---|---|---|---|
| `0GUSDT` | 2026-06-01 → 07-31 | 3 (06-01, 07-01, 08-01) | **2** |
| `BTCUSDT` | none | 1 (06-01) | **0** |

Two usable symbol-days, one symbol. M5-T2's criterion asks for out-of-sample R²; with two days the
only honest split is fit-on-one, test-on-the-other, which is a real out-of-sample test across a
month gap and also a sample of one. M8's cross-symbol comparison is not reachable at all.

**And the ceiling is structural, not a backlog item.** The Tardis free tier serves the *first day of
each month* (OD-2/D-002), so book coverage is ~12 days per symbol per year however long the pull
runs. A 24-month window yields at most 24 book days per symbol. That is the budget the whole
calibration lives inside, and it is worth knowing before designing a sweep that assumes more.

**What follows for this spec.** The generator is built and tested against what exists, and it is
built to accept a *set* of symbol-days so that adding days later is a configuration change rather
than a rewrite. Pulling more days is prerequisite to M5-T2 being meaningful, not to this task being
correct — but the two should not be confused, and `blockers.md` gets an entry rather than this
sitting in one person's head.

## Design

**Bind the simulator first.** M4-T1/T2 deliberately left `simulate_market_order` and
`simulate_sliced_execution` unbound, on the stated grounds that M5-T1 would be the first Python
consumer. It is. Binding follows M3-T1's established rules: the pinned-surface test grows
deliberately, `Fill` and `SlicedFill` cross as read-only value objects, and there is no per-tick
entry point.

**Sampling.** Instants are drawn on a fixed grid (every *N*th event, as M4's probe does) rather than
at random. A grid needs no seed and is reproducible, but event-count sampling weights busy periods
more heavily; record that sampling limitation. The criterion mentions a seed; where randomness is genuinely wanted later — a
random subsample of instants, say — it goes through a `numpy.random.default_rng(seed)` recorded in
the output's metadata.

**Sizes are log-spaced**, because the thing being fitted is a power law and linear spacing would put
almost every observation in the region where the exponent is flattest. Range and count are
configuration; the M4 probe's six points are a starting scale, not the target — a fit wants tens of
sizes, not six.

**Both schedules.** Each (instant, size) is simulated twice: once as an immediate market order and
once worked over a window. M4's measurement showed the two diverge systematically with size, so a
dataset with only one is a dataset that cannot answer whether execution style matters.

**Output.** Partitioned Parquet under `data/calibration/symbol=.../date=...`, written through
`storage.write_parquet` like everything else. Rows are derived statistics — size, slippage in bps,
level counts, flags — not book contents; they still live under the gitignored data root, because
they are dense enough per symbol-day that reconstructing something close to depth is not obviously
impossible, and there is no reason to find out.

## Data

- **In:** `data/book/symbol=.../date=...` (replayed), `data/trades/...` (ADV, via M4-T3).
- **Out:** `data/calibration/symbol=.../date=...` Parquet, plus a small JSON manifest recording
  configuration, corpus days used, and the code version — so a dataset can be traced to what made
  it.

## Invariants this task must not break

**No look-ahead.** Test 4, and M4-T3's ADV window rule: the ADV normalizing a fill on day *d* is
computed from days strictly before *d*.

**Determinism.** Test 1, byte-identical output. A calibration dataset that cannot be regenerated
makes every number downstream a claim about one afternoon — the failure M4 shipped and had to fix.

**Honest limitations.** `beyond_validated_depth` travels into every row (D-021), so M5-T2 can split
its fit and M9 can caveat the large-order end specifically rather than globally.

## Out of scope

- Fitting anything — **M5-T2**.
- Choosing which symbols to study — **OD-3**, deliberately deferred to M8.
- Pulling more corpus days. Prerequisite for M5-T2's criterion to be meaningful; tracked in
  `blockers.md`, not solved here.

## Open questions

**Q1 — how many sizes, over what range?**
Recommendation: ~40 log-spaced points from 0.001% to 10% of ADV, so the sweep is expressed in the
units M8 compares in and automatically adapts to a symbol's liquidity. Fixing base units instead
would make `BTCUSDT` and `0GUSDT` sweeps incomparable, which is the problem M4-T3 exists to solve.

**Q2 — how many instants per day?**
Recommendation: start at M4's every-5,000-events (259 instants/day for `0GUSDT`) and raise it once
the fit's standard errors are visible. 40 sizes × 259 instants × 2 schedules ≈ 20,700 rows per
symbol-day, which is ample for a two-parameter fit and cheap to generate.

**Q3 — should the sliced schedule's window be swept too?**
Recommendation: not in the first pass. Size is the axis the capacity answer turns on; adding a
duration axis multiplies the dataset before anything has been fitted. Revisit once M5-T2 has a
working fit on the size axis.
