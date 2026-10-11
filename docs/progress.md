# Progress

Dated log of what actually happened. **Newest entry first.** Absolute dates only (`YYYY-MM-DD`) —
never "yesterday" or "last week". Record what was *verified*, not what was intended; anything
unverified belongs in `blockers.md` instead.

Milestone status at a glance:

| Milestone | Status |
|---|---|
| M0 — Scaffolding & environment | **Complete** (2026-08-12), T1–T6, CI green |
| M1 — Data acquisition | **Complete** (2026-08-20), T1–T5 |
| M2 — Order book reconstruction (C++) | **Complete** (2026-08-29), T1–T3 |
| M3 — Bindings & SPSC queue | **Complete** (2026-08-29), T1–T3. OD-6 resolved |
| M4 — Impact simulator (C++) | **Complete** (2026-08-30), T1–T3 |
| M5 — Impact model calibration | T1–T3 implemented (2026-10-08/09); BTC/SOL fits/exports data-gated |
| M6 — Funding persistence model | T1–T3 implemented and verified; predictive adequacy open (B-012) |
| M7 — Strategy & backtest | T1/T2 implemented and verified (2026-10-10); T4 accounting next, before T3 |
| M8 — Comparative study | Not started |
| M9 — Analysis & writeup | Not started |
| M10 — Perf benchmarking (stretch) | Not started |

---

## 2026-10-10 — Accumulated-change audit for authorized publication

Reviewed the server work through M7-T2, fixed stale dependency guidance, and checked
publication candidates for data/build artifacts and credential patterns. Locked extension
rebuild and standalone CMake/Ninja build passed; 85 C++ and 657 offline Python tests
passed freshly. Ten network tests were deselected. Root Ruff lint/format and whitespace
checks passed. No blocking implementation defect was found in the reviewed paths;
B-009–B-012 and T4/T3 implementation remain open. See
`docs/pre-push-audit-2026-10-10.md` for scope, evidence and limits. User authorized pushing
these changes after the audit; hosted CI is not yet verified by these local checks.

## 2026-10-10 — M7-T2 constrained sizing and supported capacity

Implemented expected-net-dollar sizing with square-root marginal impact, separately
reporting supported break-even capacity. Chosen base quantity, USDT notional and ADV
fraction honor the unchanged T1 entry gate, both impact sides' common support, dated
contract minima, finite notional/ADV caps and caller-admitted validated liquidity.
No feasible profitable admitted lot returns zero. Shared cost-curve admission avoids
repeated disk loads. Zero impact never means infinite capacity or extrapolated roots.

OD-10 mechanics resolved in D-036. The existing sequencing defect is corrected: next
is T4 accounting, then T3 walk-forward. Actual BTC/SOL impact/ADV/metadata and funding
adequacy remain gated (B-009–B-012). No capacity/Sharpe/P&L results, downloads, dependency
changes or remote writes were produced; M7 remains incomplete.

Verification: 657 offline Python tests passed (55 new), ten network tests deselected;
26 isolated faults caught, including marginal/average confusion, capacity units, lot/
bound/probability/chronology defects, support intersection and shared cost admissions.
Six independent exhaustive lot-grid comparisons and actual synthetic M5/M6/T1 integration
pass. Ruff, compiled-free architecture and whitespace checks pass. C++ unchanged/not rerun
(85 passed in the preceding organization audit).

## 2026-10-10 — M7-T1 entry/exit rules and admitted cost integration

Implemented deterministic enter/wait/hold/exit intents using cumulative funding after
costs, strict probability thresholds and positive expected incremental edge. Held positions
keep their original horizon and compare continued holding against closing now; sunk
entry costs are excluded. M5 square-root sell-entry/buy-close cost quotes require supported
size/depth strata, known validation cutoffs and explicit spreads, fees and hedge costs.
M6 forecasts are bound to symbol and a fingerprint of model sources/prior/window settings;
adequacy approval must match that scope, cadence and remaining horizon. Synthetic cost
admission defaults off. No actual research approval or BTC/SOL fit was manufactured.

OD-9 mechanics are resolved in D-035: horizon and probability parameters remain explicit
required inputs, with dated pre-study selection still required for headline runs. Test
parameters are synthetic examples. B-009/B-010/B-011/B-012 remain open. Next task is
M7-T2 sizing and OD-10 specification; accounting must land before an executable T3 loop.

Verification: 602 offline Python tests passed (85 new), ten network tests deselected;
22 isolated scratch mutations caught; synthetic M5→M6→M7 integration, independent
imports, Ruff lint/format and whitespace checks passed. C++ unchanged/not rerun
(85 passed in the preceding organization audit). No downloads, dependency changes,
remote writes, strategy P&L, Sharpe or capacity results. M7 is started, not complete.

## 2026-10-10 — M6-T3 causal rolling and cumulative funding forecasts

Implemented settlement-at-a-time updates, observed-only 90-day refits, explicit cadence
resets/staleness/gap gates, and recursive joint posterior predictive funding sums.
Forecasts precede admission of the current rate; retrospective scoring is separate.
Exact one-step comparisons, diagnostic 3-/21-settlement horizons, monthly breakdowns
and predeclared prior sensitivity use the existing hash-admitted BTC/SOL corpus.

Actual 1,095 scored settlements per symbol: rolling 95% one-step coverage is 96.62% BTC,
96.35% SOL versus same-window frozen 90.14%/83.20%. One-day cumulative coverage is
95.43%/96.61%; weekly coverage remains only 73.77%/87.91%. Downside asymmetry,
February misses and residual dependence prevent clearing B-012. No prior, threshold or
horizon was selected to make results pass. Reviewed: `docs/analysis/M6-T3-rolling-funding.md`.

Verification: 517 offline Python tests passed (30 new); ten network tests deselected;
16 isolated scratch mutations caught; repeated real-data reports byte-identical;
Ruff lint/format, architecture and whitespace checks passed. C++ unchanged/not rerun
(85 passed in preceding organization audit). No downloads, dependencies, remote writes,
strategy accounting or headline metrics changed. M6 engineering is implemented; next is
M7-T1 policy specification (OD-9 partial), with model/data/accounting gates still explicit.

## 2026-10-09 — M6-T2 Bayesian funding model and adequacy checks

Implemented exact Normal-Inverse-Gamma AR(1), coefficient/variance credible intervals,
Student-t one-step prediction, joint posterior draws and conditional predictive checks.
Explicit fraction/bps units, proper baseline prior and unrestricted phi are documented
in D-033 and the just-in-time spec. No rolling logic or entry policy implemented ahead of T3.

Existing audited BTC/SOL funding corpus: fit only 276 warmup settlements (275 pairs),
freeze posterior, check 1,095 study settlements per symbol conditional on previous observed
funding. Warmup conditional replication is plausible; study nominal 95% coverage is
90.05% BTC and 83.47% SOL, with downside underprediction and BTC higher-lag residual
structure. Synthetic recovery meets acceptance; real study adequacy remains unestablished.
Reviewed findings: `docs/analysis/M6-T2-bayesian-funding.md`. Next implementation: M6-T3.

Verification: 487 offline Python tests passed (25 new), 10 network tests deselected;
13 scratch mutations caught; repeated real-data report byte-identical; Ruff lint/format
and whitespace checks passed. No C++ changes/tests rerun (85 passed in preceding audit).
Declared already-installed SciPy directly and refreshed lock dependency metadata only.
No downloads, remote writes, model tuning, strategy returns, Sharpe or capacity claims.

## 2026-10-09 — M6-T1 real BTC/SOL funding exploratory analysis

Implemented evidence-bound funding-series loading, cadence-segmented descriptive
statistics/ACF/PACF, ADF/KPSS checks, strictly prior monthly 90-day diagnostics and a
reproducible JSON/Markdown/plot command. The loader uses writer-owned storage names,
explicit fragment reads, endpoint/spacing/schema checks, prior audit hashes and stable
read checks. Reporting and CLI live outside statistical code, preserving D-031.

The actual corpus matched all 914 funding fragments: 1,371 settlements/457 days per
symbol, with 276 warmup and 1,095 study settlements at constant 8h cadence. Study funding
was positive for 76.44% of BTC and 53.06% of SOL settlements; mean funding was +0.3081
and -0.1512 bps respectively. Lag-one ACF was 0.6646/0.6691. Mixed full-period stationarity
diagnostics and SOL's negative tail require rolling/predictive validation, not a globally
stationary or profitable-carry claim. Reviewed findings: `docs/analysis/M6-T1-funding-eda.md`.
Generated unrounded results and six plots stay under ignored research storage.

Verification: 462 offline tests passed, including 34 new M6-T1 tests; 10 network tests
deselected. Eleven isolated mutations were caught across admission, chronology, cadence,
units, ACF/PACF, opposing nulls, p-value bounds and streaks. Lint/format/whitespace checks
passed. A synthetic timestamp fixture needed explicit pandas millisecond resolution;
the real corpus was unaffected and the lesson is recorded in C17. No C++ changes,
downloads, fitted Bayesian model, strategy returns or capacity claims. Next: M6-T2.

## 2026-10-09 — code organization audit and cleanup before M6

Reviewed Python layering, shared utilities, test placement, schema readability, C++
ownership/I/O boundaries and current project guidance. Removed model dependencies on
CLI tools: content hashing, book partition discovery, ordered streaming and Arrow-to-C++
conversion now have shared library homes. UTC calendar helpers no longer belong to a
dataset fetcher. Statistical model imports no longer require compiled replay. Split the
artifact validator by provenance/fit/artifact responsibilities and moved adapter tests
alongside the shared module. Updated stale M5/OD-8 guidance. Scope and formats are retained.

Verification: 428 offline Python tests passed (10 network deselected), 85 C++ tests
passed, and lint/format/whitespace checks passed. Six scratch mutations caught ordering,
mapping, hashing, date anchoring and dependency regressions; nine serialization mutations
were also rechecked and detected. A single-fragment ordering fixture initially missed
reversed file order; the new multiple-fragment/tied-timestamp fixture catches it.
Full findings, fixes and remaining maintenance work are in `docs/codebase-audit.md`.
No C++ source, study configuration, acquired data or research claims changed. M6 is next.

## 2026-10-09 — M5-T3 model serialization implementation

Added schema-1 per-symbol JSON export, strict loading and explicit stratum lookup.
Coefficients round-trip bit-identically, including a 17-significant-digit fixture.
Training boundaries, corpus days/counts, fitting date/code/source hash and input
manifest hashes accompany every artifact. Depth counts, size bands, signed-cost
flags, coverage limitations and unavailable strata are preserved. Units, nested
fields, duplicate keys/fits, finite numbers, chronological splits and evidence
coverage are checked. Validated writes replace files atomically. The fitting CLI
can optionally export to a chosen per-fold model directory.

Verification: 425 offline Python tests passed, including 33 new serialization tests;
10 network tests were deselected. Nine isolated serialization mutations were caught,
covering precision loss, schema version/extra fields, depth counts, future training
days, missing source evidence, duplicate keys, caveat loss and signed-cost clipping.
The future-day fixture was adjusted to isolate chronology from corpus-day consistency;
the intended chronological guard now causes its failure. Mutation details stay ignored
in `data/reports/m5-t3-mutation-audit.json`. Ruff checks and whitespace validation passed.
No C++ source was changed for this task. Actual BTC/SOL model export remains blocked
by missing admitted calibration partitions; no research models/results were created.

M5 implementation is complete, with empirical calibration still gated. Next task:
M6-T1 funding EDA, using the acquired BTC/SOL funding history.

## 2026-10-09 — M5-T2 impact fitting implementation

Implemented square-root primary fits, linear/power diagnostics, and explicit whole-day
chronological train/test cutoffs with a default prior 90-day window. Coefficients and
residual diagnostics are separate by symbol, side, schedule, independently validated
depth and training-only size band. Reports include held-out R²/RMSE/MAE, exclusions,
per-training-day coefficients/spread, signed target counts and extrapolation flags.
Negative fits are not clipped into admissible cost models; undefined constant-target
R² and unavailable regimes are explicit. No constant-cost fallback is provided.

The CLI admits only matching M5-T1 manifests and current quality/replay evidence; direct
Parquet-fragment reads avoid manifest/Hive schema collisions. Before/after fingerprints
reject concurrent changes. Reports, dense residual Parquet and residual plots remain
under ignored storage; deployable serialization/loader remain M5-T3. The actual BTC/SOL
fold invocation refused missing calibration partitions, as intended. No research
coefficients, capacity or Sharpe were produced, and no data was downloaded for this task.

Verification: 392 offline Python tests passed (37 M5-T2 tests), with 10 network tests
deselected. Ruff lint/format and diff whitespace checks passed. Twelve isolated mutations
were caught, covering forms, future-target leakage, row splits, target choice, depth
pooling, exclusions, one-day acceptance, residuals, future size bins, post-read hashes,
and signed-coefficient/static-rounding clipping. Audit details remain ignored under
`data/reports/m5-t2-mutation-audit.json`. C++ source is unchanged by M5-T2; earlier
engineering and acquisition evidence remains intact.

## 2026-10-08 — data-source and execution-options discussion recorded

Added `btc-sol-data-options.md` to record why snapshots plus trades cannot reconstruct missing
book history, the full-day scope of free first-of-month datasets, and the separate 401 access
restriction and 429 rate limit. Documented source roles, full historical replay, sampled-day
impact studies, continuous carry with inferred costs, cost-sensitivity prototypes, and future
live collection. One-day pilots and cross-day validation are distinguished from annual claims.
Bar-derived ADV remains an explicit unselected alternative to the current trade-derived contract.

Checked official Tardis live-streaming documentation: its free local software connects directly
to exchanges rather than receiving a hosted Tardis relay. Read-only server checks found Binance
depth WebSocket upgrade 101 and REST snapshot restricted-location status 451. No collector was
started, no purchase/download expansion was authorized by this documentation request, and no
headline coverage choice or study configuration changed. Documentation-only changes; application
tests were not rerun for this entry. Prior engineering and acquisition evidence below is preserved.

## 2026-10-08 — BTC/SOL scope, server engineering and fresh acquisition

Research realigned to BTCUSDT/SOLUSDT. Stopped both active 0G expansion processes with cleanup; existing partitions are retained. No old-machine corpus is being copied. Common scored period is 2025-10-01–2026-09-30, warmup July–September 2025, and June prehistory for strictly prior ADV. Config and study coverage are in `config/btc-sol-study.toml` and `btc-sol-study.md`; numerical capacity/Sharpe/event claims are explicitly untested hypotheses.

188 BTC/SOL archive availability probes passed (status and magic, not full-data quality). Regular October 2 book requests returned 401. Free first-of-month full-day feeds cover only 3.29% of scored days; daily replay needs additional historical access, while inferred costs require a clearly labeled model-based backtest. Headline coverage remains pending user selection.

Both symbols' July 2025–September 2026 funding histories were freshly downloaded with existing settlement guards. Spot/futures 1m price ingestion was added with separate caches, mandatory published checksums, spot microsecond normalization, complete month grids and close-time availability. Both complete price histories and the October 1 trade pilots are now acquired and validated in `data/btc-sol`. Funding combined-window audit passed: 1,371 settlements / 457 days per symbol with constant 8-hour cadence and no boundary gaps. Warmup/prehistory/late-study trade pilots completed for June 1 and July 1, 2025 and September 1, 2026; sampled books are blocked by HTTP 429 (~23-hour Retry-After), respected.

Completed M0–M4 work is preserved. M5-T1 now produces deterministic, evidence-bound calibration rows through C++ queue replay and copied checkpoints; missing ADV days, rejected/stale volume reports and unmatched book/reference hashes fail admission. No impact coefficient, Bayesian gate, backtest, Sharpe or research capacity has been fitted yet. Final broad offline suite: 355 passed, 10 network deselected; C++: 85 passed. Focused calibration/queue tests: 29 passed. Five calibration/ADV guard mutations and three price causality/grid/checksum mutations were detected. Rebuilt queue sanitizer executable passed 547 assertions / 9 cases under process-only ASLR disabling; Catch discovery still hits the documented platform mapping issue. October 10 trades are rejected for both (BTC 6.59%, SOL 6.75% volume deficits), and SOL tick estimates disagree across early/late windows; no guards were bypassed. BTC grid evidence was refreshed. The overall corpus report fails partial trade-window/continuity coverage, as expected. Final admitted trade totals: 11,122,305 BTC rows and 9,432,157 SOL rows over four days each; each of the four price series has 701,280 minute bars. `data/btc-sol/reports/study-status.json` records expected/missing days and verifies all price-output hashes. These are source records, not a claim that book events passed through the research queue.

## 2026-10-08 — pre-push documentation audit and server handoff

M5 remains draft specifications, with no calibration implementation or fitted model. The local
checkout has no historical corpus available for inspection. Earlier session reports describe 11
`0GUSDT` book days (2025-10-01 through 2026-08-01) and a trades backfill stopped by October 2025's
trade-ID guard; these reports require verification on the data host. The reported October 10
volume shortfall was approximately 4.4%; it has not been accepted or allowlisted.

The storage projection below is superseded: `0GUSDT` listed in September 2025, so 24 months of its
history were unavailable at the time. One-day storage samples do not establish a full-corpus cost
or a statistical confidence interval. Book/trades overlap also does not establish a complete
strictly prior ADV window. See the current audit note in `blockers.md` before a server backfill.

This push contains documentation only. Historical test counts below are prior-run evidence;
the Python/C++ suites were not rerun for this documentation audit.

## 2026-08-30 — bulk pull re-costed against stored Parquet and free disk (superseded)

`blockers.md` had asked for this before committing to the pull. Measured from partitions already on
disk rather than from archive sizes: the 893 MB `BTCUSDT` book archive lands as **544 MB of
Parquet** (161,057,093 rows at 3.5 bytes/row), so the storage bill is smaller than the download.

Per symbol over a 24-month window — 24 book days (the free tier serves the first of each month) and
~730 trade days: **`0GUSDT` ~0.8 GB, `BTCUSDT` ~31 GB, `ETHUSDT` ~40 GB.** Free disk: 15 GB.

**The binding decision is which second symbol, not how long the window is.** Unblocking M5 is nearly
free: `0GUSDT`'s remaining 21 first-of-month book days cost ~0.4 GB and take the calibration set
from 2 usable days to 24 — the difference between an out-of-sample R² on a sample of one and a claim
that means something. A second thin altcoin is ~1 GB. `BTCUSDT` and `ETHUSDT` do not fit at all.

That makes **OD-3** — symbol selection, which the design doc defers to M8 — a decision with a
storage consequence landing at M5. Recorded rather than resolved: the choice is still open, but it
is no longer only about which symbols are interesting.

Confidence stated with the numbers: `0GUSDT` and `BTCUSDT` are measured, trades/day varies ~7x with
volatility so those are ±50%, and the `ETHUSDT` book figure is a guess — no ETH book day has ever
been downloaded, and it is the largest unmeasured term.


## 2026-08-30 — OD-7 resolved; M5 specced (T1–T3)

**D-024 resolves OD-7** — fit both functional forms, and report **per size regime**. The design doc
anticipated the first half; the second half came from the M4 data. Fitting `slippage ~ size^alpha`
pairwise across the M4 sweep, the implied exponent climbs monotonically: 0.197, 0.411, 0.506, 0.768,
1.167. Square-root is 0.5 and linear is 1.0, so **neither describes the whole curve** and a
single-form verdict would be wrong at both ends.

Three mechanisms, worth modelling rather than averaging: small sizes are dominated by the
half-spread (a constant offset, not a power law, which compresses the apparent exponent); the
mid-range sits close to the square-root law, which is what the literature predicts and mild evidence
the simulator behaves; large sizes go super-linear as the order eats into thinner book.

Two consequences that are easy to get wrong and are now written down. **Fit against touch-relative
slippage**, since folding the half-spread into an impact coefficient double-counts it in M7 and
distorts the exponent exactly where impact is smallest. And **the super-linear regime is the least
validated part of the curve** — 94.2% of fills at 200,000 units and 99.6% at 1,000,000 walk past the
vendor's 25-level reference, so the region that departs most from square-root is the one nothing
independently checks.

**A blocker logged rather than discovered later: the corpus cannot support M5-T2's criterion.** Two
usable symbol-days (`0GUSDT` 06-01 and 07-01), one symbol. The only out-of-sample split is
fit-on-one/test-on-the-other — real, and a sample of one. The ceiling is structural: the free tier
serves the first day of each month, so book coverage is ~12 days per symbol per year regardless of
effort. M5-T2's spec carries a test that fails loudly rather than reporting an in-sample R² in an
out-of-sample field.

Also recorded in M5-T1: **M4 kept no rows.** The probe simulated 1,554 static fills and 480 sliced
runs and retained only rates and means, so there is currently no dataset to fit anything to. That is
M5-T1's job, and it begins by binding the simulator — deliberately left unbound in M4 on the stated
grounds that M5-T1 would be its first Python consumer.


## 2026-08-30 — M4 made reproducible, and M4-T2 meets real data

Answering "are we fully validated?" honestly: **M4 was not.** Three gaps, now closed.

**The published M4 numbers could not be reproduced.** The depth and slippage figures had gone into
three specs, the progress log and CLAUDE.md from a throwaway program that no longer existed. Every
other milestone here ships an artifact that says "re-run to reproduce"; a number that cannot be is
a claim about one afternoon. Now `cpp/tools/impact_probe.cpp` and
`docs/validation/M4-0GUSDT-2026-06-01.json`. It regenerates every figure exactly — 94.2% and 99.6%
past level 25, 1.50/2.37/6.10/13.77/39.95/261.32 bps, 6.2% crossed.

**M4-T2 had never touched real data at all** — synthetic fixtures only, since vendor rows cannot
reach CI. The probe now works each parent order over 10 s in 5 slices against taking it at once,
40 sampled windows on `0GUSDT` 2026-06-01:

| size | at once | worked over 10 s | slicing cheaper |
|---|---|---|---|
| 100 | 1.50 bps | 1.59 bps | 52.5% |
| 1,000 | 2.37 | 1.83 | 65.0% |
| 10,000 | 6.10 | 3.81 | 87.5% |
| 50,000 | 13.77 | 8.17 | 95.0% |
| 200,000 | 39.95 | 20.97 | **100%** |
| 1,000,000 | 261.32 | 186.22 | **100%** |

**The criterion's "slippage falls with duration" holds on real data for large orders and fails for
small ones** — precisely the caveat M4-T2's spec wrote down before any of it was measured. At 100
units slicing is *worse* on average and barely better than a coin flip per window: the order is too
small for impact to dominate, so there is nothing to save by waiting. By 200,000 it is cheaper on
every window sampled and roughly halves the cost.

**A refactor the second tool forced.** `event_csv.{hpp,cpp}` now holds the exported-events reader
that `replay_validate.cpp` had privately. A second copy of the exporter's column contract would
have been a second source of truth agreeing only by luck, failing in the direction that looks like
success — a file parsed into the wrong fields is still a plausible book (C15). Verified
behaviour-preserving: the validator still reports 277,590 images matched exactly on the same day.

Stale docs swept: the design doc's layout tree was missing `order_size.py`, `fetch_klines.py`,
`impact_probe.cpp` and `event_csv.cpp`, and still described `impact_simulator` as unwritten; the
README still said M4 was next.


## 2026-08-30 — M4-T3: order size normalization, completing M4

`ingestion/fetch_klines.py` (D-022's independent volume reference) and `models/order_size.py`
(%ADV and %depth). 312 offline + 10 network Python tests, 85 C++, ruff clean. 4 mutations run, 4
caught — including the look-ahead one, where the ADV window slips to include the day it is
normalizing.

**The criterion's cross-check agrees exactly, not within a tolerance.** D-022 declined to pick an
epsilon in advance, on the grounds that one chosen before seeing the discrepancy is one chosen to
pass. Measured: volume summed from the `trades` corpus against Binance's published daily bar, for
`0GUSDT` on 2026-06-01, 2026-07-01 and 2026-07-15 — **identical to the last bit on all three**,
across a 20x range in daily volume. The test asserts exact equality. Same outcome as M2-T2, where
the strict criterion also turned out to be available.

**This is the first evidence that the trades ingest is complete.** Every other check in this project
is internal — schema, `trade_id` contiguity, partition dates — and every one of them passes on a
corpus that is simply missing rows the venue had. Two independent aggregations of the same trades
agreeing exactly is a different kind of claim.

**What normalization bought immediately: M4-T1's depth limit, in units that compare.** The base-unit
version said nothing about whether a size was large. Against June's ADV for the same symbol
(21.9M units/day, matching the 2026-06-01 book probe):

| order size | % of ADV | fills past level 25 |
|---|---|---|
| 50,000 | 0.23% | 0.0% |
| 200,000 | 0.91% | 94.2% |
| 1,000,000 | 4.57% | 99.6% |

**The validated-depth boundary sits between roughly 0.25% and 0.9% of ADV**, and a capacity study
sweeps from about 0.1% upward. So the small-order end of the curve rests on validated book state and
most of the interesting range does not. That sentence is worth far more than "the book is validated
to 25 levels", and it only became sayable once sizes could be normalized — which is the argument for
M4-T3 existing at all.


## 2026-08-30 — M4-T2: time-sliced execution

`simulate_sliced_execution(updates, side, quantity, schedule)`. 85 C++ tests (was 72), 293 Python,
ruff clean. Takes a *schedule*, not a policy: TWAP and VWAP differ only in the weights, so the
caller supplies them and the volume-profile question stays out of the core.

**D-023, forced by a test written for something else.** The draft had each slice call M4-T1's
read-only `simulate_market_order`. Test 4 then failed and exposed why: with a frozen book, four
slices of 5 units each saw *undepleted* liquidity and filled at the same average as one slice of 5,
so a 20-unit parent came out cheaper than a single 20-unit order — free money from relabelling, and
unbounded in the number of slices. Exactly the error a capacity study must not make.

Slices now consume. `execute_market_order` does the same walk and depletes what it took;
`simulate_market_order` stays const, because M5 still sweeps many sizes against one instant. Both
behaviours are pinned by a test so neither can quietly become the other.

The approximation is stated rather than hidden: a later vendor update at a touched price carries an
*absolute* quantity, so it overwrites the footprint and our impact decays as the real book refreshes.
Crude — the data describes a world where we did not trade — but decay taken from the data rather
than assumed, and it is what makes "spreading an order over time is cheaper" a measured effect here
instead of a construction.

**Four mutations, four caught — after one survived, and the reason was C16 again.** Losing the
remainder on the last slice passed, because the fixture used 10.0 split three ways, where the naive
per-slice share happens to sum exactly in IEEE double. Rather than assume a divergent case existed,
I searched for one: 7.0 split as 2:5:0.5:1 sums to 6.999999999999999, one ULP short. With that
fixture the mutation dies. Second time this session that a test stood exactly where two rules agree.

The look-ahead mutation — applying every update before the first slice — is caught by two tests.
That is the invariant ranked first in the north star, and a time-sliced simulator over a replayed
stream is the most natural place in the project for it to enter.


## 2026-08-30 — M4-T1: static book-walk simulator

`simulate_market_order(book, side, quantity)` in `perpcarry_core`. 72 C++ tests (was 60), 293
Python, ruff clean. 8 mutations run, 8 caught — including the two that would have been wrong in the
flattering direction: capping the walk at level 25, and filling an oversized order's remainder at
the last price rather than reporting partial fill.

**D-021's flag was measured, and it is a sharper instrument than expected.** Sweeping buy sizes at
259 sampled instants on `0GUSDT` 2026-06-01:

| size (base units) | walked past level 25 | mean slippage vs mid |
|---|---|---|
| 100 | 0.0% | 1.50 bps |
| 10,000 | 0.0% | 6.10 bps |
| 50,000 | 0.0% | 13.77 bps |
| 200,000 | **94.2%** | 39.95 bps |
| 1,000,000 | **99.6%** | 261.32 bps |

The transition is sharp and sits inside the range a capacity study cares about. That converts a
vague caveat — "the book is validated to 25 levels" — into a usable statement: the small-order end
of the capacity curve rests on validated state and the large-order end does not, with the boundary
locatable per symbol. Only available because the flag is per-fill rather than a note in a document.
M5-T1 should measure it properly across symbols; this was a throwaway probe, not a committed tool.

**Crossed books at 6.2% of sampled instants**, independently matching the 6.3% of updates measured
in M2-T2. So M4-T1 Q1's decision to flag rather than refuse is load-bearing: refusing would silently
discard one instant in sixteen, on a rule chosen before seeing whether those fills are anomalous.

**One deviation from the spec as drafted.** `average_price` is NaN when nothing filled, not 0.0.
The struct comment said 0 and the test table said "no average price rather than a zero"; the test
won. A zero is a valid-looking price that would average into a calibration dataset without
complaint, where a NaN propagates to whoever forgot to check `filled_quantity`.

Bindings deliberately not added: M5-T1 is the first Python consumer, and M4-T2 will change the
surface again.


## 2026-08-30 — M4 specced (T1–T3)

All three in `docs/specs/M4/`. No open design decision gates M4; OD-5 (L2, D-017) constrains it
hard and is already resolved. Two decisions logged that the design doc did not specify.

**D-021 — the depth problem is disclosed per fill, not capped.** The book is validated 25 levels
deep and M4-T1 walks deeper, for exactly the large orders the capacity answer is about. Every fill
now reports `levels_consumed` and `beyond_validated_depth`, so the approximation travels with the
number into M5's dataset and M9's curve rather than being described once in a document. Capping the
walk at level 25 was rejected explicitly: it makes large orders look *cheaper* than they are — the
error runs in the flattering direction — and bounds the capacity answer by an artifact of the
reference dataset while looking like caution.

**D-022 — ADV is computed from trades and cross-checked against klines.** M4-T3's criterion said
"tested against known ADV figures" and no known figures existed; the venue API is geo-blocked, so
the only ADV available was one derived from our own corpus, and testing that against itself is the
trap M1-T4 shipped and M3-T3 nearly repeated. `data.binance.vision` publishes daily klines whose
`volume` is the venue's own aggregation of the same trades, and `klines_daily_url` already exists
from M1-T1. Worth noting what this check would catch that nothing else can: a trades ingest that
silently dropped rows. Every existing check is internal, and all of them pass on a corpus that is
merely missing data.

**Three things the specs say that the design doc's criteria do not:**

1. M4-T1's criterion ("unit tests against hand-computed book-walk examples") is necessary and
   nowhere near sufficient. Hand-computed cases check arithmetic on books someone chose; they say
   nothing about the shapes a real day produces. Measured: **82,356 of 1,299,113 updates on
   `0GUSDT` 2026-06-01 leave the book crossed** — 6.3%, so a simulator sampling at random lands
   there constantly. Walk it, flag it, let M5 decide; a mid that sits outside the spread is not
   something to regress on silently.
2. M4-T2's criterion says slippage *decreases* with longer duration. That is only true if the book
   replenishes, which a synthetic test book does by construction and a real trending window may not.
   Written down now so nobody later "fixes" the simulator until real data reproduces a synthetic
   property.
3. `OrderSide::Buy` is a distinct type from `Side::Bid`. A buy consumes the *ask* side, and reusing
   one enum for both is how a sign error gets written that reads correctly.

M4-T3 is Python rather than C++, deviating from the milestone heading: normalization needs symbol
identity and committed metadata, and `perpcarry_core` has deliberately avoided data dependencies.


## 2026-08-30 — closing the three gaps the pre-push audit left open

**Linux/GCC is no longer inference.** The branch had only ever been built with clang on macOS, and
three things met the other platform for the first time. Verified in containers (`gcc:14`), both
architectures:

| | arm64 | x86_64 |
|---|---|---|
| build warnings | 0 | 0 |
| `ctest` | 59/59 | 59/59 |
| `hardware_destructive_interference_size` | 256 | **64** |
| TSan `[spsc]` | clean | — |

The x86_64 value settles the M3-T2 claim on evidence rather than on one machine: 64 there, 256 on
Apple Silicon, so hard-coding the tutorial's 64 really would under-pad by 4x on the development
machine. The `-Winterference-size` pragma was also shown to be load-bearing — removing it makes
GCC warn, with the note that the value "can vary between compiler versions or with different
-mtune".

**`size_approx()`'s ordering fix now has a test that fails without it.** The previous commit said
plainly that it did not. A third observer thread reading the queue while producer and consumer run
catches the tail-first version 3 runs out of 3. The bound is "no underflow", not `<= capacity` — an
observer sampling head early and tail late may legitimately see more than a queue-full, and writing
the tighter assertion would have made the test wrong rather than strict.

**The macOS duplicate-library warning is gone**, and not by restructuring a correct dependency
graph. `perpcarry_tests` genuinely depends on `perpcarry_core` directly and also receives it
transitively through the validator; declaring direct dependencies directly is right, so the fix
silences Apple's warning for that target rather than dropping the explicit edge and making the
tests' link quietly depend on the tools being enabled.


## 2026-08-29 — M3-T3: end-to-end pipeline, completing M3

`Pipeline` in `perpcarry_core` (ingest thread → SPSC queue → replay thread), bound to Python;
`perpcarry.tools.run_pipeline` drives it from Parquet. 292 Python tests (was 281), 59 C++, ruff
clean.

**Real run: `0GUSDT` 2026-06-01, 1,299,113 events in ~3.5s — exactly the count M2-T2 recorded**, so
the checkpoint's first half matches. The queue saturated: peak occupancy 65,536 of 65,536 with
160,255 producer stalls, so the contention this task exists to exercise happened on real data and
not only in the synthetic test. Recorded in `docs/validation/M3-T3-0GUSDT-2026-06-01.json`.

**Determinism demonstrated rather than argued.** The digest `e35d9045…` was identical across three
runs and across queue capacities of 8 versus 65,536 — an interleaving difference of 439,648 stalls
against 160,255. That is D-020's constraint holding on a real day. An independent cross-check fell
out of it: the final book is 400 bid / 998 ask levels, exactly what M2-T3's "close" ladder sample
reported for the same timestamp by a different code path.

**A latent CI break fixed before it fired.** Nothing linked `Threads::Threads`, so M3-T2's
`std::thread` stress test linked on macOS and would have failed on Linux/libstdc++, which needs
`-pthread`. Caught by looking rather than by CI.

**Two definitions revised in the open:**

1. `dump_csv` is now bound to Python, reversing M2-T3's "and probably never". That call reasoned
   Python can read the corpus directly — true, and beside the point: the checkpoint is a digest of
   the *replayed* book, which only C++ holds. Re-deriving the rendering in Python would agree today
   (`repr(float)` and `std::to_chars` both emit shortest round-trip) and that coincidence is exactly
   what C15 warns is invisible until it breaks. The human-readable renderings stay unbound.
2. The threaded pipeline sits in `perpcarry_core`, not `tools/`: it does no file I/O, and the
   bindings link only the core. It is the sole threaded thing there, and the book core is still not
   concurrent — the `OrderBook` is owned entirely by the consumer thread.

**Five mutations, five caught,** including two that matter more than they look: removing the
consumer's abort signal *hangs* the pipeline (a producer blocked on a queue nobody drains — a worse
failure than an exception, since a hang carries no message), and transposing the price and quantity
columns in the Arrow conversion yields a run that completes, reports the right event count, and
builds an entirely wrong book. No count check in this project would have noticed the second.


## 2026-08-29 — M3-T2: lock-free SPSC queue, and TSan wired into CI

`cpp/include/perpcarry/spsc_queue.hpp` (header-only, bounded ring, power-of-two mask,
placement-new into raw union storage so a non-trivial element is constructed and destroyed exactly
once), 8 Catch2 cases / 544 assertions, a 10M-item two-thread stress run. 59 C++ tests (was 51),
281 Python, ruff clean.

**B-008 closed: ThreadSanitizer now runs in CI.** A `PERPCARRY_SANITIZER` CMake option plus a
`sanitizer` job building `-fsanitize=thread` and running the `[spsc]` tag — per-PR, not the nightly
tier the design doc specifies and which still does not exist, because the run costs ~4s and a rigor
claim CI does not run is a claim about the past (C10). **Verified to catch something:** weakening
the queue's release/acquire pair to `relaxed` produces a reported race and a non-zero exit, clean
exits zero. `TSAN_OPTIONS=halt_on_error=1` so a race fails the job even when that run's assertions
do not notice it.

**Throughput: median 55.8M items/sec, range 43.0–59.7M** (`BookUpdate`, 40 bytes, capacity 65536,
arm64, clang, RelWithDebInfo) — `docs/validation/M3-T2-throughput.json`.

Two things measurement changed:

1. **A single sample was not a measurement.** Consecutive uncontrolled runs ranged 35.6M–46.1M, a
   ~25% spread wide enough that any one could be quoted as the answer. The tool now repeats 7 times
   and reports median/min/max, and records that warm in-process repeats read ~57M against ~46M for
   separate invocations — the real pipeline sees the cold case.
2. **The cache-line padding claim was folklore until it was checked.** Interleaved padded/unpadded
   runs, 8 pairs to control for machine drift: padded 46.1–48.9M, unpadded 40.1–43.8M, no overlap.
   Real, and worth ~15% — much less than tutorials imply. An uninterleaved first attempt at the same
   comparison was pure noise, which is the honest reason for interleaving.

Also measured rather than assumed: `hardware_destructive_interference_size` is 256 here, so the 64
every SPSC tutorial hard-codes would have under-padded by 4x on this architecture.


## 2026-08-29 — M3-T1: pybind11 bindings

`cpp/bindings/pybind_module.cpp` grows from a `version()` stub to the real surface: `Side`,
`BookUpdate`, `ReplayStats`, `OrderBook`, `BookReplayer`, `BookReplayError`. 17 test items in
`tests/test_bindings.py`; 281 Python tests (was 264) and 51 C++ tests green, ruff clean.

**Levels cross as copies, deliberately.** `OrderBook::levels()` returns a span its own header
documents as invalidated by the next `apply()` — correct on the C++ side, where it lets M4 walk the
book without allocating. Handed to Python as a view it becomes an object that keeps returning
numbers and returns garbage after the next update, surfacing as a plausible fill price rather than
as a crash. The binding builds a fresh list, which makes that structurally impossible.

**A second lifetime hazard the spec had not named.** `BookReplayer::book()` returns a C++
reference; bound with `reference` rather than `reference_internal`, `book = r.book(); del r` reads
freed memory. Now pinned by a test that segfaults deterministically under the mutation.

**Six mutations, six caught — after one survived.** Narrowing `levels()`'s output to `float` passed
the entire suite, because the round-trip test asserted only through `best_bid()` and `levels()` is a
separate emitting path — the one M5 actually walks for depth. The test now covers both. Same lesson
as C16 in a different costume: a test aimed at a property has to cover every path that produces it,
not just the first one written.

**Deliberately not bound:** the M2-T3 renderers and `compare_top_n`/`BookDiff` (harness's job, on the
far side of a licence boundary), and any single-row entry point on `BookReplayer` — Risk R4, now a
test rather than a comment. The PyArrow→`BookUpdate` conversion is left to M3-T3, where it has a
consumer.


## 2026-08-29 — OD-6 resolved; M3 specced (T1–T3)

OD-6 resolved as option (b) — single-threaded core plus an SPSC queue (D-020), design doc Status
line updated. Two points recorded that §6 did not make: option (c) cannot be benchmarked honestly,
since a backtest replays one totally ordered stream and has no concurrent writers for per-level
locking to protect against; and the queue may change *when* an item is consumed but never *which* or
*in what order*, so no simulation behaviour may depend on occupancy or producer timing. That second
one is a determinism constraint, and M3-T2 makes it a test rather than a comment.

**Three drifts found reviewing M3 against the codebase, all folded into the specs:**

1. **M3-T1 is no longer on the validation path.** Its criterion ("book state queried from Python
   matches C++ fixture tests") was written assuming bindings would validate the book against vendor
   data. D-018 closed that loop through the CSV harness instead, precisely because M3-T1 depends on
   M2-T2. The spec says so, and redirects the Python tests at the *boundary* — ordering, truncation,
   float fidelity, lifetimes — rather than re-asserting book semantics that 51 C++ tests already
   cover, which would be C15's two-copies-of-one-assumption in a second language.
2. **`OrderBook::levels()` returns a span invalidated by the next `apply()`.** Bound naively that is
   a dangling view into Python that keeps returning plausible numbers. M3-T1 requires a copy at the
   boundary and a test that fails on a zero-copy binding.
3. **M3-T3's "M2-T2 checkpoint" names an artifact that has never existed** — grepped; the word
   appears nowhere outside the design doc. Defined in the M3-T3 spec as the committed JSON counts
   plus a SHA-256 of M2-T3's `dump_csv`. The dump is pure and deterministic so the digest is stable,
   and a digest is publishable where the dump plainly is not (Tardis 9.2(2)).

**TSan is now owned rather than inherited.** `blockers.md` had it as an unassigned gap; M3-T2's spec
puts the build work inside that task, in the per-PR CI tier rather than the nightly tier that does
not exist (C10).


## 2026-08-29 — M2-T3: book state debug serialization

`format_price`, `dump_csv`, `format_ladder` and `format_diff` in `perpcarry_core`
(`cpp/include/perpcarry/book_debug.hpp`, `cpp/src/book_debug.cpp`); the harness's one-line-per-level
stopgap replaced by the side-by-side ladder, plus clean-run sampling. 50 C++ tests (was 36) and 264
Python tests, all green; ruff clean; wheel rebuilt and `perpcarry_cpp` imports.

**Verified against real data, not only fixtures.** `0GUSDT` 2026-06-01 through
`perpcarry_replay_validate`: 277,590 images, verdict `pass`, 2.4s, three samples rendered at
00:00:01.245, 12:00:00.034, 23:59:59.598. Then the failure path on a scratch copy of the same day
with one reference quantity perturbed — the defect was found and rendered as a marked ladder, and
the truncation's own ambiguous mismatch carried the `AMBIGUOUS PAIRING` caveat. Nothing was written
under `data/` or into the repo; scratch copies deleted.

**Seven mutations, seven caught — after one survived.** Replacing `to_chars` with `%.8f`, echoing
the depth back as the ladder's level count, re-deriving the diff's rank window, dropping the
ambiguity caveat, dropping the close sample, printing clean samples on a failing run, and anchoring
the midday target to the first image instead of the UTC day. The last one *survived* initially:
the fixture's day opened at exactly 00:00:00.000, where both candidate rules give the same answer.
Moving the fixture's open to 00:00:00.137 — which is what a real export looks like — made the
distinction observable and the mutation was then caught. Recorded as C16.

**One draft claim retracted.** The spec said a CSV dump would be `diff`-able against a pyarrow
reference export. It is not: shortest round-trip and pyarrow's rendering disagree textually on
values they agree on numerically, and round-trip is the property that has to win. The header
comment and the spec now say to compare values, not lines.


## 2026-08-29

### M2-T2 complete — replay validated against the vendor's own book, on real data

`BookReplayer` + `compare_top_n` in the core, plus the local harness D-018 called for:
`python -m perpcarry.tools.export_book` writes two CSVs, `perpcarry_replay_validate` replays and
compares. 16 Catch2 tests and 10 pytest tests; **12 of 12 mutations caught**. Suite is 36 C++ and
264 Python tests.

**Both real-data runs pass.** Summaries committed under `docs/validation/` — aggregated counts
only, which is what the licence permits.

| | `0GUSDT` | `BTCUSDT` |
|---|---|---|
| Coverage | full day, 1,299,113 events | first 20,000,361 events (~12%) |
| Images compared | 277,590 | 287,193 |
| Unambiguous | 105,142 | **0** |
| Mismatches | 0 | 0 |
| Resyncs | 13 | 1 |
| Crossed observations | 82,356 (6.3%) | 2,011,452 (10.1%) |
| Wall time | 2.3 s | 13.4 s |

The `0GUSDT` resync count of 13 independently reproduces `fetch_book.ingest`'s figure for the same
day from a separate implementation in another language, and the unambiguous count of 105,142
reproduces the numpy analysis that set the spec. Two independent routes to the same numbers.

**The criterion had to be revised, and the measurement is why (D-019).** The spec asserted only on
*unambiguous* images — those whose millisecond holds exactly one event, where the pairing is forced.
`BTCUSDT` has **zero** of those in 287,193 images: at ~1.9 events per millisecond, nothing is ever
alone in its millisecond. So the criterion was vacuous on the one symbol M2–M4 actually replays.
It now asserts on every image, which is *stricter* — it covers 459,641 images the old rule only
counted — at the cost of one stated assumption about when the vendor emits an image, backed by
564,783 observations with no counter-example.

**A check that has never failed on real data is not known to work on real data (C12), so it was
made to fail.** Deleting one top-of-book update from the real `0GUSDT` events produced 10
mismatches, correctly categorised as quantity mismatches at the expected timestamps.

**Two findings came out of that, both kept:**

1. **Only the top 25 levels are validated at all.** The first injection attempt deleted an update
   at `0.3997`, deep in a ~1000-level book — and the harness passed. No reference image describes
   that depth. By level count the check constrains ~2.5% of the book, and M4 walks far deeper for
   large orders. On the watch list, to be settled when M4-T1 is specced.
2. **A dropped update self-heals.** Those 10 mismatches stopped once the next update at that price
   arrived: L2 diffs carry absolute quantities, not deltas. Reassuring about the data, and a reason
   any corruption window is narrower than it looks.

**One defect found in my own tooling before it could be blamed on the book.** The first `BTCUSDT`
run reported exactly one mismatch, at precisely the last exported timestamp. Cause: `--max-events`
cut inside a 150-event millisecond, so the final image reflected updates the export had dropped.
The exporter now rounds up to the millisecond boundary, and the case has its own test. Worth
recording because the symptom — one mismatch in 287,193 — is exactly what a subtle replay bug
looks like, and it was neither subtle nor in the replay.

**The pre-push audit caught a third silent hole, in the build rather than the code.** Configuring
with `-DPERPCARRY_BUILD_TOOLS=OFF` dropped all seven validator tests while `ctest` still printed
"100% tests passed" — 29 where 36 were expected, with no outward difference. CI never sets that
flag, so nothing was broken today; the hole was that a future edit could turn the entire M2-T2
mechanism off and stay green. The combination is now a hard CMake error. Same shape as C15: a check
that passes by not running.

Two smaller audit findings, both fixed before the commit: `docs/grill-me.md` (a personal skill file)
was swept in by `git add docs/`, and the summaries' `produced_at_git_sha` pointed at the commit
*before* the one containing the code that produced them — the sha of the introducing commit cannot
be known while producing it, so the field now describes its provenance instead of asserting a wrong
one.

**Verified this session:** `uv sync --locked`, `ruff check`, `ruff format --check`, `uv run pytest`
→ 264 passed, 6 deselected; clean-dir `cmake` configure/build + `ctest` → 36/36; the tools-off
configure fails with the intended message. Mutation sources restored to pristine and re-verified
green.

---

## 2026-08-22

### M2-T1 complete — `OrderBook`, 14 tests, 9 of 10 mutations caught

`cpp/include/perpcarry/order_book.hpp` + `cpp/src/order_book.cpp`. Sorted `std::vector<Level>` per
side, bids descending and asks ascending, `quantity == 0` erasing. First real code in `cpp/` beyond
the `version()` stub.

**The acceptance criterion — agreement with an independently-reconstructed reference — is a
differential test against an in-test `std::map` book**, 100k seeded operations with *both sides
compared in full after every single operation* (0.25 s). The two implementations are structurally
different, which is the point: they fail differently.

**Mutation results (C12), read as detections rather than failure counts:**

| Mutation | Caught by |
|---|---|
| Bids ordered ascending | `a better price moves top of book…` (+4 others) |
| Removals never erase | `quantity zero removes the level` |
| Removing an absent level throws | `removing a level that is not in the book is a no-op` |
| Existing price inserts a duplicate | `an update at an existing price replaces it in place` |
| `is_crossed` uses `>` not `>=` | `a crossed book is reported, not repaired` |
| Price validation removed | `invalid prices and quantities are rejected` |
| Quantity validation removed | same |
| `clear()` forgets the ask side | `clear empties both sides` |
| `best()` returns the worst level | `a better price moves top of book…` |
| **`reserve()` removed** | **nothing — survived, by design** |

The survivor is honest and stays: `reserve()` changes when allocation happens, not what the book
contains. Asserting on `capacity()` would pin an implementation detail. It is recorded in the
spec's Q1 rather than quietly rounded away in a "9/9" claim — the count is 9 of 10.

The differential test caught nothing during development, which is worth stating plainly: the
implementation was right the first time, and the test's value is entirely in the mutation table
above. A green differential run on its own would have been no evidence at all.

**Two deviations from the spec as drafted**, both now recorded in it: `depth()` renamed
`level_count()` (Q3 taken — M4-T3's "depth" is a quantity, and the collision would have crossed the
pybind11 surface), and `BookUpdate` deferred to M2-T2 since nothing in T1 consumes it (C5).

**One portability trap avoided.** The randomised stream uses `rng() % n`, not
`std::uniform_int_distribution`: distributions are not portable across standard libraries and CI
runs both libc++ and libstdc++, so a distribution-based stream would differ between the two legs
and a CI failure would not reproduce locally. Probed and confirmed the same day that AppleClang 21
has `std::span`, `std::optional` and floating-point `std::to_chars` — the last being what M2-T3's
round-trip number formatting rests on, and the one libc++ historically lacked.

**Verified this session:** `uv run cmake --build build/dev` + `ctest` → **15/15 passed**;
`uv run ruff check .` and `ruff format --check .` clean; `uv sync --reinstall-package perpcarry`
then `uv run pytest -q` → 254 passed, 6 deselected. Source restored to pristine after the mutation
run and re-verified green.

### M2 specs written; OD-5 resolved; the replay tolerance measured rather than assumed

Wrote `specs/M2/{M2-T1,M2-T2,M2-T3}`. No code yet. Three things came out of the writing that were
not known before it.

**OD-5 confirmed as L2 (D-017), on a stronger reason than the design doc's.** §6 argued L2 as
"standard practice"; the real constraint is that after OD-2 the only reachable book source is
price-level aggregated at the source, so no order-level alternative existed to choose against.
Consequence carried into M4 and the M9 caveats: queue position is unknowable, so the simulator can
model marketable orders and cannot model a resting limit order's fill probability. Design-doc
Status line updated.

**M2-T2's "within documented tolerance" is a partition, not an epsilon.** Measured on `0GUSDT`
2026-06-01 against the corpus already on disk:

| Quantity | Value |
|---|---|
| Incremental rows / distinct ms | 1,299,113 / 414,207 (non-decreasing in file order) |
| Reference images (exactly 50 rows each) | 277,590 |
| Images whose ms holds no incremental row | **0** — and none with a gap of ±10 ms either |
| Incremental rows sharing an image's ms | mean 3.83, median 2, p99 28, max 1,452 |
| Images whose ms holds exactly one | **105,142 (37.9%)** |

So there are no quiet points to compare at — the vendor emits an image on book change, so every
image shares a millisecond with the diff that produced it. A design that waits for a gap would have
had nothing to compare on the thinnest symbol in the corpus, and that would have been discovered at
implementation time rather than now. The tolerance is therefore: **exact** equality (bitwise, 25
levels per side) on the 105,142 images whose pairing is forced, and a reported mismatch rate on the
rest, whose intra-ms ordering is unrecoverable because *our own* µs→ms truncation (D-013) removed
it. Not an epsilon — an epsilon wide enough to absorb the ambiguous set would be wide enough to
hide a real defect.

**Book depth measured, and it settles the data structure.** Opening snapshot blocks hold 1,013 bid
/ 1,002 ask levels for `BTCUSDT` and 403 / 1,000 for `0GUSDT` — the feed caps around 1,000 per
side, so a side is ~16 KB and a sorted `std::vector` beats a node-based map for the linear walk M4
performs on every simulated order. Also found: **BTC's opening snapshot block contains 13
zero-quantity rows**, so a replayer that treats removal-of-an-absent-level as an error cannot ingest
the first 2,015 rows of a real day. That is now test 5 of M2-T1 rather than a bug in week two.

**The validation path needed a decision (D-018).** M2-T2's criterion assumes Python feeds the
replayer (D-012), but the bindings are M3-T1, which *depends on* M2-T2 — and the Tardis licence
means the comparison can never run in CI anyway. Resolved as a local-only harness: a Python CSV
exporter plus a `perpcarry_replay_validate` C++ tool outside `perpcarry_core`, with only the
aggregated JSON summary committed. Rejected pulling M3-T1 forward (inverts the doc's edge, violates
C5). The C10 gap this leaves is logged on the blockers watch list rather than absorbed.

**Verified this session, before writing any of it:** `uv run pytest -q` → 254 passed, 6 deselected;
`uv run cmake --build build/dev` + `uv run ctest` → 1/1 passed; `import perpcarry_cpp` → `0.1.0`.
So M2 starts from a green tree and a stub-only `cpp/`.

---

## 2026-08-20

### M1 pipeline exercised end to end; four findings, none of them code defects

Ran the whole M1 ingestion path against real data at realistic scale, per M1-T3's Q1 ("pull 3
months to exercise the pipeline before committing to the full 24"). The code needed no changes.
Everything below is a fact about the data or the plan that the exercise surfaced.

**The streaming design holds at the size it was built for.** `BTCUSDT` 2026-06-01
`incremental_book_L2`: **161,057,093 rows in 323 bounded chunks**, 47,781 snapshot rows,
17,311,007 removals, 13 resync events — 893 MB compressed in, 570 MB Parquet out. The matching
`book_snapshot_25` melted to **115,452,150 rows in 231 chunks**. Nothing was held whole at any
point. That 17.3M removals is also the strongest argument yet for preserving `amount = 0`: it is
11% of the feed, not an edge case.

**The spec's book size estimate is about half the truth.** M1-T3 Q1 budgets ~449 MB/day for BTC
book; measured 893 MB for 2026-06-01, plus 84 MB for the reference. The 24-month plan is therefore
**~23 GB for BTC book alone**, not the ~10.8 GB budgeted, before Parquet and before ETH. Logged to
`blockers.md` — the bulk pull needs re-costing against actual free disk (currently ~13 GiB).

**Tardis does not answer `HEAD`.** It returns 404 where `GET` returns 200. A `HEAD`-based sizing
probe therefore reports every book dataset as absent and undercounts the total by its largest term
— which is exactly what happened on the first attempt at estimating this pull. Nothing in the
codebase uses `HEAD`, so no code was affected, but the trap is worth knowing before anyone sizes
the 24-month pull.

**Monthly archives lag the month, and `backfill` is month-granular.** `0GUSDT-trades-2026-08.zip`
and the matching `fundingRate` both 404 on 2026-08-20 while daily `trades` files exist through
2026-08-19. So the current month cannot enter the corpus at all through `backfill`, and the study
window has to end at the last complete month unless a daily fallback is added.

That is not cosmetic, and the validator proved it: the Tardis book **is** available for
2026-08-01, so pulling everything available produced a corpus whose book data sits outside the
trades window, and `book_within_trades_window` fired on it. Calibrating impact on a day the
backtest has no execution data for is precisely what that check exists to stop. Decide the window
question before the bulk pull, since it changes what "24 months" means.

**Corpus as it stands** (deliberately partial — this was an exercise, not the bulk pull):
`0GUSDT` 61 trade days and 61 funding days (June–July complete months) plus 3 book days; `BTCUSDT`
1 book day. 2.0 GB on disk including the 1.2 GB download cache. `validate_data` reports 680 checks
with 2 failures, both of them the known incoherences above rather than data defects — the August
book day with no August trades, and BTC book with no BTC trades pulled.

### M1 complete — T4 data validation, and a broken invariant it exposed

`ingestion/validate_data.py` plus the committed `ingestion/data_quality_allowlist.toml`. 43 tests;
suite now 251 offline + 6 network, all green. **26/26 mutations caught.** 15 checks across
integrity, completeness, consistency, plausibility and the order book.

**Validated against a real assembled corpus**, not just fixtures: 0GUSDT June 2026 — 30 trade days
(2.37M trades), 30 funding days (180 settlements), one book day (1.3M rows) and its reference.
**354 checks, zero failures**, including the exact klines volume reconciliation on all 30 days.

**The headline finding: `trade_id` contiguity is not a property of this venue, and never was.**
Building that corpus was the first time a *full month* went through `fetch_trades.backfill`, and it
refused immediately — 154 gaps in 0GUSDT 2026-06. Characterised: 157 absent ids across 2,366,674
trades, every run 1 or 2 long, no duplicates, no time discontinuity. The decisive test was the
independent one — on 2026-06-01 (4 gaps) and 2026-06-15 (6 gaps) summed trade quantity equals
summed 1m klines volume **exactly**. Ids are skipped; trades are not lost.

So the design doc's M1-T1 criterion was unsatisfiable, audit assumption A7 was false, and both the
fetcher and this validator were enforcing a rule real data does not obey. All four are corrected
(D-015): gaps are now classified against `MAX_ID_SKIP`, with the klines equality carrying the
actual completeness guarantee. The general lesson is the one worth keeping — **an invariant
confirmed on a sample is a hypothesis, not a property.** A7 had been checked against a 200-row
fixture and a few days; the first full month falsified it.

**A second bug, and this one my tests were actively hiding.** The validator located funding
partitions with `fetch_funding.DATASET`, which is `"fundingRate"` — the *archive's* name, appearing
in URLs. The fetcher stores under `funding/`. So the validator looked in a directory that never
existed, found zero partitions, and reported everything fine. It passed the whole suite, including
a test whose stated purpose was that every check actually runs, because **the fixture had hard-coded
the same wrong path**. It only surfaced when a real corpus was pointed at it.

Fixed structurally rather than by correcting the constant: both fetchers now export a `STORAGE_DIR`
the validator reads, and the fixture builds its corpus by calling the fetchers' own `store()`
functions, so a future divergence fails loudly. Recorded as C15.

Also corrected: the allowlist is TOML rather than the spec's YAML (D-016) — `tomllib` is stdlib
where PyYAML would be a new runtime dependency for one config file. And the book schemas now keep
the vendor's `exchange` column, which was previously discarded; it is the only venue-tagged field
anywhere in the corpus, and without it the spec's "a mixed-venue corpus is rejected" test had
nothing to test. The validator is explicit that trades and funding cannot be checked this way and
reports those as skipped rather than passed.

**The pre-push audit found the checksum check was a no-op**, which is the finding worth keeping
because of what it was a no-op *about*. `archive_checksums` built its URL as
`{BASE}/{filename}` — but the archive nests by period, dataset and symbol
(`{BASE}/monthly/trades/0GUSDT/...`), so every request 404'd, `fetch_checksum` returned `None` for
a missing `.CHECKSUM`, and the loop skipped the file. All 42 cached archives were skipped, the
check yielded **zero results**, and the report read clean.

That is precisely the false confidence the module's own docstring is about — written into the one
check whose entire job is integrity. It survived because nothing tested the opt-in network path,
and because a check that yields nothing looks identical to a check that yields all-passes.

Fixed by reconstructing the URL from the filename (`binance_archive.url_for_filename`, which has
to handle klines naming their *interval* where every other dataset names itself), and by making an
unverifiable file a **reported failure** rather than a silent skip — being unable to verify a file
is not the same as the file being sound. Verified against the real cache: 42 archives, 42 results,
all passing, where it previously produced none.

**Network checks are opt-in and reported as skipped, never as passes** — archive checksum
re-verification and the klines reconciliation both need a live host, and a gate that silently
reports success without running is the false confidence this task exists to prevent.

### M1-T3 complete — historical L2 order book acquisition

`ingestion/fetch_book.py` + `ingestion/tardis_archive.py`. 61 tests (59 offline, 2 network); suite
now 204 offline + 6 network, all green. **19/19 mutations caught.** This is the data the project's
central claim rests on — that execution costs are *calibrated* rather than assumed — so the
fidelity obtained here bounds what M9 may honestly assert.

Verified against real vendor data (0GUSDT 2026-06-01): 1,299,113 incremental rows in 3 chunks,
19,799 snapshot rows, 63,764 removals, 13 resync events; and 277,590 book images melted to
13,879,500 reference rows. 10.2 MB + 11.0 MB on disk.

**Two spec assumptions were wrong, and both failed loudly only because a guard existed.**

**`book_snapshot_25` is not shaped like the incremental feed.** The spec listed it as the
validation reference without saying it is a **wide 104-column table** — one row per book image with
`asks[0].price` … `bids[24].amount` as columns — not one row per level update. The first real run
died with "missing columns ['amount', 'is_snapshot', 'price', 'side']". It is now melted to long
form on ingest (D-014), which turns M2-T2's comparison into a join rather than a reshape of 104
bracketed names. Melting multiplies rows by up to 50, so the read chunk shrinks by the same factor
for that dataset — otherwise the bounded-memory property is lost exactly where the files are
largest.

**Every vendor URL for a symbol ends in the same basename.** The date lives in the path
(`.../2026/06/01/0GUSDT.csv.gz`), and `cached_fetch` keys its cache on the filename — so a 24-month
backfill would have downloaded June once and served that same file for all 24 months, and for both
datasets. Silent, and it survives every schema and integrity check. The Binance archive never
exposed this because its filenames carry the date. Caught by the stray-day guard, which existed for
an unrelated reason: a mismatched day tripped it, and the mismatch was the cache. `cache_path` now
builds the key from dataset, symbol and date, and three tests pin it.

Worth recording as the general lesson: **a guard written for one failure mode caught a different
one.** The stray-day check was defending against misfiling rows into the wrong partition; what it
actually found was a caching bug two layers away. Cheap invariants pay out in places you did not
plan for.

**Two things the review then corrected, both about honesty of reporting rather than correctness.**

`resyncs` counted *rows*, not events. A real resync is one ~1,400-row book image, so the day read
as "18,396 resyncs" when the true figure is **13**. Nothing computed a wrong number, but M2 reads
this field to decide how often its replayer must reset state, and three orders of magnitude is not
a rounding difference. Now `resync_events` and `resync_rows`, with a test that a block split across
a chunk boundary still counts once.

And the docstring justifying D-013 claimed the vendor's capture latency is "frequently
sub-millisecond". Measured, it is not: p1 1.48 ms, median 2.04 ms, p99 516 ms. The decision to keep
`latency_us` still stands, but for the accurate reason — **99.8% of rows are not a whole number of
milliseconds**, so converting first loses the detail on essentially every row. The claim now matches
the measurement.

**Licence handling.** Every fixture in the test module is synthetic, which is a licence requirement
rather than a style choice: Clause 9.2(2) forbids redistributing raw rows, and committing a real
book day would publish vendor data through the repo and push it into CI. There is a test asserting
no vendor book fixture is ever committed, and the two tests that touch real vendor data are marked
`network` so they never run in CI (C10).

**Not done, deliberately.** The 24-month bulk pull. The spec's Q1 says to exercise the pipeline on
a few months before committing to ~10.8 GB for BTC, and that is now possible — but it is a large
download and belongs in a deliberate run, not a side effect of finishing the task.

### M1-T5 complete — symbol tick/step derivation

`ingestion/derive_symbol_meta.py` plus the committed `ingestion/symbol_meta.json`. 48 tests (47
offline, 1 network); suite now 144 offline + 4 network, all green. **14/14 mutations caught.**
Resolves B-007, which had been blocking M2, M4-T3 and M7-T2 with no obtainable authoritative
source.

**The pre-push audit found the confidence logic was counting its own evidence wrong**, and this is
the finding worth keeping. `combine` pooled windows by **summing** their per-window distinct
counts, so a price observed on all three days counted as three pieces of evidence. The threshold
it feeds is justified by a probability argument over *distinct* values, so the error inflated
confidence — and it inflated it most where the windows overlap most, which is precisely where they
are least independent. Wrong direction, quietly.

It also meant the committed `distinct_prices` field did not hold a distinct count, and a second,
smaller version of the same bug sat underneath: deduplication was on the CSV *text*, so an archive
emitting both `1.0` and `1.00` would have counted one grid point twice.

Fixed by carrying the distinct observations themselves through `GridEstimate` and pooling by union,
with dedup on numeric value. The corrected counts, re-derived: `BTCUSDT` 68,703 → 65,187 distinct
prices, `ETHUSDT` 30,995 → 26,835, and quantities roughly halved (`ETHUSDT` 99,215 → 49,412) since
trade sizes repeat across days far more than prices do. **No tick or step value changed and all
three symbols remain confident by a wide margin** — the conclusions were never at risk, but the
reported evidence was overstated by up to 2x.

Worth noting what did *not* catch it: 12/12 mutations, a full suite, and a network test that
agreed with hand-verified values. Every one of those checks the value; none checked whether the
number attached to *how much we should believe it* meant anything. The two mutations added for the
pooling logic now do.

**The re-derivation reproduced the spec's hand-verified table exactly** — tick, step, per-window
distinct-price counts and trade counts, for both `0GUSDT` and `ETHUSDT` across all three days.
That is the strongest available evidence the implementation matches what was measured by hand on
2026-08-12, since the spec's numbers were produced by a different throwaway probe.

Added `BTCUSDT` (tick `0.1`, step `0.001`, 11.7M trades, 65,187 distinct prices) — it is the
symbol whose book data M2–M4 replays, and the design doc never listed its tick as a dependency
either. Symbol coverage stops there deliberately: OD-3 is open and deferred to M8, so the table
grows when the study symbols are chosen.

**Two bugs found by the tests, both mine, both silent-wrong rather than loud.** The dtype guard
checked `dtype != object`, which is right for pandas 2 and wrong for pandas 3 — this project runs
3.0.5, where `read_csv(dtype=str)` yields `StringDtype`, so the guard rejected every real archive
frame. Now it checks the *element* type, which is the property actually meant. And `sample_days`
built its month midpoint from 1-based month numbers, putting the middle window a month late and,
on a single-month range, inventing a second window *after* the end date.

**Design notes worth carrying forward.**

- `decimal_gcd` **rejects** floats rather than converting them. A silent conversion is exactly the
  bug that produces a plausible number and no error, and `Decimal(0.1)` is not one tenth.
- Scaling is done on the digit tuple, not `scaleb`, so the active decimal context cannot round a
  long price on the way through.
- Confidence is pooled across windows, not judged per window: three thin days that agree are
  better evidence than any one of them. Below 20 distinct values the estimate is reported
  low-confidence, and `--write` refuses to commit it.
- Cross-window disagreement is an **error**, never resolved by taking the finest value. Two
  different causes produce it — a window too thin to resolve the grid, or the venue re-ticking the
  symbol mid-study — and they call for opposite responses.

**The mutation run's one survivor was a rendering choice, and closing it needed a different kind
of test.** Dropping `normalize()` leaves the step size as `1.0` where the grid is `1` — numerically
identical, so no equality assertion can see it, and my first attempt at a test read the *committed
file*, which already held the normalised text and passed either way. The test that catches it pins
the rendering of a freshly derived value. Worth remembering: when the property under test is how a
value is *written* rather than what it *is*, asserting against the stored artifact tests nothing.

Verified: 141 offline + 4 network green, ruff clean, and the committed JSON confirmed present in a
built wheel (`wheel.packages` carries package data, but a missing lookup table would only surface
at M2).

### Blocker sweep, and B-002 resolved as D-012

No code changed. Suite re-verified before and after: **97 offline passed, 3 network deselected**,
`ruff check` and `ruff format --check` clean.

**B-006 was stale and had been for eight days.** It sat in Active claiming to be "the main open
item before implementation" — but OD-11 resolved it on 2026-08-12, the same day it was raised,
via exactly its own recommended path (fee as a swept parameter, manually-sourced dated base-case
table). Nothing was wrong with the decision; the blocker just never got swept when the OD closed.

Filed the general lesson with it: **resolving an OD does not close the blockers that cite it.**
`blockers.md` is read as steering at the start of a session, so a false Active entry costs a
future session real time — it is worse than no entry.

**B-002 resolved as D-012** — Python owns all Parquet I/O; the C++ core takes an in-memory batch
across pybind11 and does no file I/O at all. This was the adjacent gap: §2's diagram drew storage
feeding the core directly while §10 listed no Arrow C++ dependency, and nothing would have failed
until M2-T2 or M3 tried to write the read.

Chosen over adding Arrow C++ because it is what Risk R4's pipeline-level boundary already implies,
because Arrow C++ would land in the wheel build, the standalone CMake path, and four CI legs to
duplicate what PyArrow does in the process that wrote the file — and because the performance
argument for a native reader is a guess until an M10 profile exists. The cost is stated rather
than hidden: replay input is materialised before it crosses, so peak memory scales with batch
size. Reversible behind the same `BookReplayer` interface if profiling ever justifies it.

Propagated so the documents no longer disagree: §2's diagram routes storage → core through a
Python replay driver, §2's rationale and §10's storage bullet state the no-file-I/O rule, and
`CLAUDE.md`'s "five known gaps" line now reflects the two that are actually still open.

**Active blockers are now B-004 and B-007 only** — B-004 a standing constraint rather than a task,
B-007 resolved by implementing M1-T5.

---

## 2026-08-12

### Stale documentation swept

Retired advice and statuses that later findings had overtaken:

- **The "start a recorder now, every day of delay is lost data" urgency is withdrawn** from
  `blockers.md` and the audit. It was correct only while OD-2 option (a) was live; every source the
  project now uses is a static historical archive, so nothing decays while a decision is pending.
  The residual argument against dawdling is precedent, not decay — `bookTicker` was published for
  ten months and then simply stopped.
- **B-001, B-003 and B-005 moved to Resolved** with their resolutions recorded. B-004 (geo-blocking)
  stays Active as a standing constraint rather than an open task — nothing in scope needs the live
  API.
- **Three watch-list items retired** as done: CI has run and is green, network tests exist and are
  marked, and M1-T1's `trade_id` criterion was settled by naming the `trades` dataset.
- **Funding cadence corrected everywhere** — audit A12, design doc §3.3, M1-T2's spec. Earlier text
  said majors are 8h and thin symbols 4h; `0GUSDT` actually ran 4h → 1h → 4h within a year, so the
  interval is not a per-symbol constant and must be read per row.
- **Added a watch-list entry for M6**: an AR(1) fit over a window whose sampling frequency changes
  mid-way is not sampling one process throughout. Better raised in M6-T2's spec than found at fit
  time.
- `CLAUDE.md` and `README.md` now state what actually exists and works, including that nothing needs
  to run continuously.

### M1-T2 complete — funding rate downloader

`ingestion/fetch_funding.py`, reusing `binance_archive.py` and `download.py`. 28 tests (27 offline,
1 network); suite now 90 offline + 3 network, all green. 10/10 mutations caught.

Both fixtures are real archive months so the hard cases are genuine: `BTCUSDT` 2026-06 exhibits the
actual ~1 ms jitter, and `1000BONKUSDT` 2026-06 carries the real upstream gap found during the
audit. A test asserts the fixture still jitters — if the source stops, the tolerance it justifies
would be silently untested.

**Mutation testing led to deleting a branch rather than testing it.** The first implementation
measured each settlement step against the *earlier* row's interval, which misreads a 4h→8h
re-cadence as a missing settlement, and compensated with a skip for pairs straddling a change. No
test could distinguish that skip present or absent. Measuring against the **later** row — the
cadence the settled period actually ran under — is correct in both directions with no special case.
A test now fails if the choice is reverted.

Worth noting as a pattern: a mutation surviving is not always a missing test. Sometimes it means
the branch has no behaviour worth having.

**The review then found the completeness check skipped itself on exactly the interesting months.**
It compared settlement count against `24 / interval × days`, defined only for a single cadence — so
any month containing an interval change passed with no coverage check at all. Found by running it
against `0GUSDT`'s real listing month: **233 settlements where a full month allows 180**, accepted
without complaint.

That month also produced a data finding worth carrying into M6/M8: **`0GUSDT` settled every 4h at
listing (2025-09-17), then every 1h from 2025-09-22**, returning to 4h by 2026-06. The cadence is
not a symbol constant, let alone a global one. Hard-coding 8h would misstate a 1h symbol's
annualised funding by 8×.

Completeness is now **continuity plus endpoint coverage**, which holds whatever the interval mix.
A late start is legitimate and reported; a short end is a defect. The exact-count check is kept
where meaningful, since it alone catches an interval column that disagrees with the actual cadence.
`backfill` now returns its reports rather than only logging them — M1-T4's allowlist and the M9
caveats both need them. 11/11 mutations caught afterwards; suite 97 offline + 3 network.

### M1-T1 complete — trades downloader

`ingestion/fetch_trades.py` + `binance_archive.py` (URL construction, shared with the remaining M1
fetchers). 22 tests: 21 offline against a 200-row real-archive fixture, 1 `network`. Suite now 54
offline + 2 network, all green.

**The spec's predicted bug happened — through an unpredicted mechanism.** The spec flagged the
aggressor-side mapping as "the single easiest thing to get backwards, with no loud failure mode".
It did go wrong on first write, but not by inverting the condition: the CSV is read with
`dtype=str` to preserve precision, so `is_buyer_maker` arrives as the *strings* `"true"`/`"false"`,
and `bool("false")` is `True`. `.astype(bool)` therefore labelled **every trade a sell**, uniformly
and silently. `test_real_fixture_has_both_sides` caught it on the very first run.

Worth recording as a general lesson: the spec was right that the area needed a dedicated test, and
wrong about how it would break. Predicting *where* risk lives is useful even when predicting *how*
it manifests is not.

Two behaviours chosen deliberately: `date` is derived per-trade from the timestamp (so monthly
archives split into correct daily partitions), and `backfill` refuses to skip a missing month
unless `allow_missing` is passed — a 404 before a symbol's listing date is explainable, but
explainable gaps must be acknowledged rather than absorbed. Skipped months are returned for M1-T4's
allowlist.

Verified by mutation: **7/7 injected defects detected**, each by exactly one named test. The
`network` test confirms the exact klines reconciliation against the live archive.

**The pre-push review then found six more things, one serious.** Tests were not isolated from the
real data root, and `cached_fetch` writes into `data/.cache/` under the *archive's own filename* —
so a test's synthetic payload had left a 199-row punched fixture sitting in
`data/.cache/0GUSDT-trades-2026-08.zip`. A later real backfill would have reused it as genuine
archive data. Fixed structurally: an autouse `conftest.py` fixture repoints `PERPCARRY_DATA_ROOT`
per test, with tests asserting the cache stays inside it (C9 updated).

Second substantive finding: `backfill` never checked `trade_id` continuity **across** month
boundaries, though the criterion says "within and across days" — a wholly missing file between two
intact months would leave both looking perfect. Also fixed: duplicates reported as "gaps" despite a
different cause, `klines_volume` skipping the checksum verification every other download performs,
and a docstring claiming exactness it did not provide.

Then mutation testing found **three of those fixes were themselves untested** and passed with the
fix deleted. Now caught, and recorded in C12: code written in response to a review is at least as
likely to be under-tested as code written the first time.

Asking what the suite still did *not* cover then found two more: **`backfill` could store nothing
at all** and every test passed (all coverage was of refusal paths, none of the happy path), and a
monthly archive whose rows spill into the next month **silently loses them** to
`delete_matching` — two rows in, one row gone, demonstrated. Both now guarded and mutation-checked.

Final state: 64 offline + 2 network tests green, `data/` empty after a full run, and 7/7 mutations
on `fetch_trades.py` caught.

### All M1 open questions resolved — specs ready to implement

Licence read first, since it gated M1-T3. Every remaining question was then settled by measurement
rather than judgement.

**Licence (Tardis ToS, read in full).** Free samples fall under the standard terms; "Permitted Use"
is *internal business, research, educational or personal use*, so the project's core use is
licensed. Clause 9.2(2) forbids redistributing the Data, permitting only aggregated calculated
Derived Data from which raw data cannot be reconstructed. Practical effect: fitted coefficients,
capacity curves and plots are publishable; **raw book rows must never be committed, published, or
reach CI** — stricter than C9, and it rules out real vendor rows as test fixtures. One residual
ambiguity: publishing research findings is not expressly addressed, only redistribution of data.
Worth a confirmation email before M9; not a blocker before then.

**Measured resolutions.**

- **Volume reconciliation is exact, not approximate.** Summed trade quantity equals summed 1m
  `klines` volume with zero difference across `0GUSDT`, `DOGEUSDT` and `ETHUSDT` — the last with
  1.9M fractional-quantity trades, where float error was the plausible worry. Both float64 and
  `Decimal` agree. The criterion is now an equality in both the design doc and the specs.
- **Thin symbols settle every 4 hours, not 8.** BTC/ETH/DOGE are 8h; `0GUSDT` and `1000BONKUSDT`
  are 4h. OD-1's "8h for most symbols" is true for majors and false for exactly the class of symbol
  M8-T2 studies — anything hard-coding 8h would halve the altcoin's annualised funding.
- **A real upstream data gap**: `1000BONKUSDT` has 179 June settlements where 180 are expected, an
  8h hole after 2026-06-24 00:00 UTC. First concrete case for M1-T4's allowlist, and a better test
  fixture than anything synthetic.
- **Vendor days are UTC-aligned** — verified by downloading a full book day: 00:00:01.245Z to
  23:59:59.598Z, opening with a real `is_snapshot` block. Book and trade days align with no offset.
- **Book size scales steeply with liquidity**: 449 MB/day for BTCUSDT but **10 MB** for `0GUSDT`.
  Pulling several altcoin candidates is nearly free; the storage decision is about BTC alone.
- **Integrity signal for vendor files**: truncated `.gz` raises `EOFError` on inflation, so a
  partial download cannot pass silently. The vendor publishes no checksums.

**Decisions taken:** 24-month book window (2024-09 → 2026-08), trades continuous over the same span
plus a month of lead-in, funding fetched to contract inception, three disjoint days for tick
derivation, `data_quality_allowlist.yaml` for acknowledged gaps, validation nightly on non-vendor
fixtures.

**Correction.** The earlier claim that `0GUSDT`'s tick is `0.01` was wrong — a probe bug taking the
`min` of decimal exponents rather than the `max`, truncating precision 100×. It is `0.0001`,
reproduced across three disjoint days. Corrected in the audit, blockers and M1-T5. Exactly the
failure mode M1-T5's test 1 now pins: a plausible wrong number, not an error.

### M0-T6 implemented — the ingestion layer can now actually download

`python/perpcarry/ingestion/download.py`: streamed `fetch` with bounded retry, SHA-256
verification against the archive's published `.CHECKSUM`, `cached_fetch`, and `extract_csv` for
zip/gzip/plain. Added `httpx` (D-011) — the project previously had no HTTP client at all, which
blocked every M1 task. 18 tests; suite now 32 offline + 1 network.

Network tests are marked and **deselected by default** (`addopts = "-ra -m 'not network'"`), so CI
never depends on a live archive (C10). The one network test downloads a real funding archive,
verifies its published checksum, and asserts the 90-row/8h shape — it passes.

**Mutation testing found a decorative test.** `test_no_partial_file_survives_a_failure` used an
HTTP 500, which fails *before* any bytes are written — so no `.part` file ever existed and the test
passed even with the cleanup code deleted. It asserted nothing about the behaviour it was named
for. Replaced with a mid-stream failure that streams real bytes and then drops the connection.

Final result: **6/6 injected defects detected**, each by exactly one precisely-named test — better
targeting than the storage suite, where one defect lights up five tests.

Two notes for M1: the vendor publishes no `.CHECKSUM` files (404), so book downloads need a
different integrity signal — gzip inflation succeeding is the obvious candidate. And the mutation
harness must back up to a scratch copy rather than `git checkout` when the file under test is still
untracked; the first run silently accumulated all five defects instead of reverting.

### Design adjusted to the audit; OD-1, OD-2, OD-11 resolved

The audit's ten recommended edits are applied to `design-doc.md`, and propagated to the M0 and M1
specs. **Three open decisions closed** (D-009): Binance USD-M throughout, book data from the Tardis
free tier, fees as a swept parameter with a dated base-case table.

Design doc changes: §3.2 rewritten around the vendor's actual schema (adds `is_snapshot` and
`local_timestamp`, **drops `update_id`** — the feed has none, so dropped-update detection is
snapshot-comparison rather than sequence-based, and is weaker); §3.3 drops `mark_price` and adds
`funding_interval_hours`; §3.4 gains a storage footprint; §4.1 rewritten around static file
downloads with the geo-block stated; M1-T1/T2/T3 and M2-T2/T3 acceptance criteria rewritten to be
satisfiable; §7, §8 (R1 retired, R8 added), §9 and §10 updated.

**Two new tasks** (D-010), both dependencies the design never listed: **M0-T6** — the project has
no HTTP client at all, which blocks every M1 fetcher — and **M1-T5**, symbol tick/step derivation,
needed by M2, M4-T3 and M7-T2 with no obtainable authoritative source.

Specs now written: `M0/M0-T6`, `M1/M1-T1`, `M1-T2`, `M1-T3` (was Blocked, now unblocked), `M1-T4`,
`M1-T5`.

**Still open, both deliberately:** how many months of book data to pull (~449 MB/day compressed),
and the vendor's free-tier licensing terms, which have not been read and must be before the data
is relied upon.

### External-dependencies audit — 13 assumptions checked, OD-2 resolvable

`external-dependencies-audit.md` sweeps every claim the design doc makes about an external
service, each verified by calling the service from this machine rather than reading docs. Four
assumptions broken, two gaps needing a decision, and one finding that unblocks the project's
highest-risk dependency.

**The unblock:** Tardis.dev's free tier serves `incremental_book_L2` for `binance-futures` with no
API key — first day of every month, back to at least 2020, snapshot + diffs with `amount = 0` for
level removal, matching §3.2 exactly. Same venue as the deep trades/funding archive, so the project
keeps single-venue integrity *and* gets true L2. Sparse coverage is fine because M5 calibrates a
model and M7 consumes the model, never the raw book.

**Broken assumptions:** funding history has no `mark_price` (§3.3); "the venue's public endpoints"
(§4.1) are geo-blocked; M2-T2/M2-T3's "venue REST snapshot" and "exchange UI" validation routes are
unreachable — replaceable with Tardis `book_snapshot_25`; `trade_id` contiguity holds only for the
`trades` dataset.

**Two open decisions before implementation:** no machine-readable historical fee schedule exists
(B-006 — and taker fees are the same order as the funding edge, so this can flip the result's
sign), and symbol tick/step size has no specified source (B-007 — inferable from trades data by
GCD, verified, but currently specified nowhere).

Ten specific design-doc edits are listed at the end of the audit. Not yet applied — they change the
user's authored document and should be reviewed first.

### M1 specs written; two findings that change OD-2

Specs for all four M1 tasks are in `docs/specs/M1/`. Written against the venue's actual data rather
than its documentation — every claim below was verified by downloading and inspecting real files.

**M1-T1 (trades)** and **M1-T2 (funding)** are cleanly specified and unblocked: the Binance archive
carries both, is current through 2026-08-01, and is not geo-blocked. Concrete details that would
have been guessed wrong otherwise: the funding archive schema is `calc_time,
funding_interval_hours, last_funding_rate` — no `symbol`, and **no `mark_price`**, which Section
3.3 specifies; and settlement timestamps jitter by 1 ms, so naive integer-hour differencing reports
a phantom "7-hour" gap.

**M1-T3 (order book) stays blocked**, and the evidence changes the decision (B-005): OD-2 option
(c) does not exist as described. `bookDepth` is not an order book — it is cumulative depth at 12
percentage bands, ~30s sampling, no sequence numbers — and `bookTicker` (L1) was discontinued after
2024-03-30. There is nothing for the M2 replayer to replay, so "start with (c) to unblock M2" is
not an available path, and M1-T3's acceptance criterion is unsatisfiable under it.

Compounding that (B-004): **Binance's REST and websocket APIs are geo-blocked from this location**,
as is Bybit. OKX works and serves true L2 with `seqId`. So Binance is the better source for history
and an unavailable one for live capture. A fourth option not in the design doc — run the project on
OKX end to end — is now the most direct route to the stated criterion.

**M1-T4 (validation)** is specified with a note that the criterion's word "unexplained" requires an
allowlist of acknowledged gaps, or it is either unachievable or satisfied by weakening the checks.

### M0-T4 round-trip test strengthened

The partitioned round-trip test was weaker than its acceptance criterion. It coerced dtypes with
`.astype(...)` before comparing, and `assert_frame_equal` defaults to `check_exact=False`
(rtol 1e-5) — so it could see neither a dtype regression nor a precision loss.

Demonstrated concretely: with `write_parquet` silently multiplying every float by `1 + 1e-9`, the
**old suite reported 7 passed**. The rewritten suite fails 4 tests on the same defect.

Rewritten with exact comparison (`check_exact=True`, `check_dtype=True`), no coercion, and the two
real deviations asserted explicitly instead of silently corrected: partitioned reads move partition
columns to the end, and do not preserve row order across fragments. Added coverage for the Hive
on-disk layout (`symbol=.../date=...`, which Section 3.4 requires and nothing had checked), both
branches of the previously untested `overwrite` flag, and `dataset_path`. 7 tests → 12.

Verified by mutation rather than by passing: **4 of 4 injected defects detected** — float32
downcast, 1e-9 perturbation, partitioning ignored, `overwrite` ignored — each caught by at least
one test whose name identifies the cause; the clean tree passes 12/12.

Read the *detection*, not the failure count. One defect can trip five tests simply because every
test round-trips through `write_parquet`; that is overlap, not five independent checks. The
best-targeted mutation (`overwrite` ignored) produced the smallest count — a single failure in
`test_rewrite_is_idempotent_when_overwriting`. When debugging a storage regression, start from the
narrowest failing test name.

Lesson saved as C12, and M0-T4's acceptance criterion in the design doc sharpened to say *exact*
equality.

### CI pipeline added (M0-T5)

`.github/workflows/ci.yml`: two jobs — `python` (ruff, format check, pytest) and `cpp` (standalone
CMake configure/build/`ctest`) — each across `ubuntu-latest` and `macos-latest`. Rationale and the
tiering plan are in design doc Section 4.9; decisions in D-007.

Every step verified by running its exact command locally before commit. That caught a real defect:
`FETCHCONTENT_BASE_DIR` set as a workflow `env:` var does nothing, because CMake reads it only
from `-D`. As written it would have run green forever while caching an empty directory. Now passed
explicitly at configure time and confirmed to populate `.fetchcontent/`. Lesson saved as C11.

Also narrowed `requires-python` from `>=3.11` to `>=3.12` (D-008) — 3.11 was an untested claim —
and raised the CMake Python floor to match. `uv sync --locked` caught the stale lockfile
immediately, which is the check working as designed.

**First run green on all four jobs** — `python` and `cpp`, on `ubuntu-latest` and `macos-latest`
([run 31655822011](https://github.com/nmokey/perpetuals-carry-strategy/actions/runs/31655822011)).
The Linux legs mattered most: the project had only ever been compiled by AppleClang on arm64, and
it builds clean under GCC too. M0's acceptance criteria are now enforced per push rather than
verified once by hand.

### M0 re-verified from a clean clone

Prompted by a challenge to the "M0 complete" claim, all four criteria were re-run against a fresh
`git clone` rather than the working tree: build 114/114, `import perpcarry` + `perpcarry_cpp` OK,
`ctest` 1/1, pytest 9/9, ruff clean. Criteria hold as written.

Caveats surfaced in the process, now all addressed: the M0-T4 partitioned round-trip test coerced
dtypes unnecessarily and compared with a tolerance — **resolved**, see the entry above. The C++
core remains a deliberate stub (C5). And "passes" meant "passed once, on one Mac" — which is what
M0-T5 exists to fix.

### Agent-orchestration docs scaffolded

Added `docs/specs/` (per-milestone subdirectories plus a spec template), `north_star.md`,
`conventions.md`, `decisions.md`, `blockers.md`, and this file. `CLAUDE.md` now points at them as
standing steering.

Seeded conventions C1–C9 from lessons already learned, including the standing rule that **no
remote action happens without explicit approval, preceded by an adversarial self-audit** (C1, C2).

### M0 complete — scaffolding & environment setup

All four M0 tasks done, each acceptance criterion verified by a command actually run:

| Task | Deliverable | Verified by |
|---|---|---|
| M0-T1 | CMake build + `uv`-managed env | `uv sync` builds `perpcarry_cpp`; `import perpcarry` succeeds |
| M0-T2 | Catch2 integrated | `uv run ctest` — 1/1 passing |
| M0-T3 | pytest + ruff | 9/9 pytest passing; `ruff check` and `ruff format --check` clean |
| M0-T4 | Parquet I/O helper | Round-trip, partition-pruning, and projection tests in `tests/test_storage.py` |

Structure created: `cpp/{include,src,bindings,tests}` with a deliberately trivial `version()` core
(stub only — see convention C5), `python/perpcarry/{ingestion,models,strategy,reporting}` package
skeleton, `python/perpcarry/storage.py` with Hive partitioning by `symbol`/`date`, root `tests/`
suite, gitignored `data/`.

Decisions taken: D-001 through D-006 (see `decisions.md`). Notably `editable.rebuild` is off after
hitting a stale-toolchain-path failure (D-003 / C8). OD-13 and OD-14 resolved, with their Status
lines updated in the design doc.

### Design doc reviewed for self-consistency

Dependency graph is acyclic and milestone stopping points are coherent. Five gaps found and
logged: B-001 (OD-2 unresolved), B-002 (no C++ Parquet reader specified), B-003 (book schema
assumes diffs the interim data source lacks), plus three watch-list items in `blockers.md`.

### Repository initialized

Git repo created on `main`, remote set to `github.com/nmokey/perpetuals-carry-strategy`. M0
scaffolding pushed as commit `4b2b00e` (approved before the C1 convention existed; all subsequent
pushes require explicit approval).
