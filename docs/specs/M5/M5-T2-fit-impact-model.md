# M5-T2 — Fit impact model(s)

**2026-10-11 readiness:** All expected BTC/SOL samples have passing replay reports and
futures-bar ADV is complete. Generate admitted calibration rows before actual fits. Historical 0G
overlap/R² discussion below is not the current server corpus; see
[status](../../current-status.md) and [D-040 volume evidence](../../analysis/bar-volume-adv.md).

**Milestone:** M5
**Status:** Implemented 2026-10-09; synthetic verification complete, BTC/SOL research fits data-gated
**Depends on:** M5-T1; OD-7 (primary square-root, linear/power diagnostics; D-026/D-029)
**Design doc:** Section 4.5, Section 5 (M5), OD-7

## Goal

Fit execution cost as a function of order size, compare the candidate functional forms, and report
the comparison with out-of-sample diagnostics. This is the moment the project's central claim
becomes checkable: from here on, the entry threshold and position sizing are driven by a
relationship measured from book data rather than by a number someone chose.

## Acceptance criteria

Copied verbatim from the design doc Section 5 table:

> Documented comparison of functional forms (OD-7); out-of-sample R² reported

Expanded into checkable tests:

| # | Test | Where |
|---|---|---|
| 1 | On synthetic data generated from a known square-root law, the square-root fit recovers the true coefficient to within tolerance and beats the linear fit | `tests/models/test_impact_model.py` |
| 2 | The mirror case: on data generated from a known linear law, the linear fit wins. Both directions, so "square-root always wins" cannot pass | same |
| 3 | Out-of-sample R² is computed on data the fit never saw, and is reported per form | same |
| 4 | The train/test split is **by day**, never by row — rows within a day are not independent observations | same |
| 5 | Fitting uses **touch-relative** slippage; a run against mid-relative is either refused or recorded as such in the output (D-024) | same |
| 6 | Coefficients are reported separately for fills inside and beyond the validated depth (D-021), and the row counts of each are in the output | same |
| 7 | Rows flagged `crossed_at_entry` or `exhausted_book` are excluded from the fit by default, and the exclusion count is reported rather than silent | same |
| 8 | A fit on too few days to hold one out fails loudly rather than reporting an in-sample R² as if it were out-of-sample | same |
| 9 | Residual diagnostics are produced (residuals vs fitted, vs size) and the fit is deterministic given the same dataset | same |

Test 2 exists because test 1 alone is satisfied by a procedure that always prefers square-root, and
D-024 predicts square-root will look good in the mid-range — so the test that would catch a
rigged comparison is the one where linear must win.

Test 8 is not hypothetical: see the data ceiling below.

## Active BTC/SOL scope

The primary law is regression-calibrated square-root impact. Linear and free-exponent fits are diagnostics; they must not replace the requested primary law or force a favorable coefficient. Fit separately by symbol/schedule and validated-depth regime, using completed strictly prior days in chronological folds. The common period and monthly sampling limitation are defined in `docs/btc-sol-study.md`. Historical 0G counts below are engineering context, not active calibration coverage.

## What OD-7's historical resolution (D-024) established

Three things this spec inherits rather than re-decides:

1. **Fit both forms and report per size regime.** The M4 sweep shows the implied exponent climbing
   from 0.197 to 1.167 across the size range, so no single form describes the whole curve and a
   single-winner verdict would be wrong at both ends.
2. **Fit against touch-relative slippage.** The half-spread is a separate cost that M7 accounts for
   on its own; folding it into an impact coefficient double-counts it downstream, and it distorts
   the exponent most where impact is smallest.
3. **The super-linear large-order regime is the least validated part of the curve.** At 200,000
   units 94.2% of fills walk past the vendor's 25-level reference, and at 1,000,000 it is 99.6%. The
   regime that departs most from square-root is the one whose underlying book nothing independently
   checks. Report the coefficient; report the caveat with it.

## The data ceiling, and what this task may honestly claim

**2026-10-08 correction:** the overlap counts below are historical and do not verify complete
prior ADV coverage. Use the current `blockers.md` audit note and verify the corpus on the data
host. The M4 aggregate exponents motivate this comparison; they do not establish that either
candidate must lose or that one form cannot describe touch-relative costs.

M5-T1 records it; this is the task it constrains. As of 2026-08-30 there are **two usable symbol-days**
(`0GUSDT` 2026-06-01 and 2026-07-01) and the Tardis free tier caps book coverage at ~12 days per
symbol per year.

With two days, the only out-of-sample split is fit-on-one, test-on-the-other. That is a genuine
out-of-sample test across a month gap, and it is also a sample of one: a single R² from a single
held-out day says almost nothing about whether the fit generalises. **The criterion is met in form
and not in substance**, and the spec says so now rather than letting a reported number imply
otherwise.

Test 8 exists so this cannot degrade silently: a run with fewer than two days must fail rather than
report an in-sample R² in an out-of-sample field. Pulling more first-of-month days is the unblock,
and it belongs on the watch list rather than inside this task.

## Design

**Two forms, one framework.** Both are linear regressions after transformation, so neither needs a
solver: square-root fits `slippage ~ a·√(size/ADV)`, linear fits `slippage ~ b·(size/ADV)`, and a
free-exponent power law `slippage ~ c·(size/ADV)^α` is fitted as a third for diagnosis — it is not a
candidate model, it is how the regime structure D-024 observed gets quantified rather than eyeballed.

**Size enters normalized** (%ADV, from M4-T3), not in base units, so coefficients are comparable
across symbols when M8 arrives.

**Diagnostics are part of the deliverable, not a debug aid.** Residuals vs fitted and vs size are
what would reveal that a single form is being stretched across regimes — exactly the failure D-024
predicts. A reported R² without them is a number that cannot be argued with.

**No Bayesian machinery here.** That is OD-8's subject and applies to funding (M6). This is
least squares on a transformed variable, and its simplicity is a feature: the interesting content is
the comparison and the caveats, not the estimator.

## Data

- **In:** `data/calibration/symbol=.../date=...` from M5-T1.
- **Out:** fitted coefficients and diagnostics, handed to M5-T3 for serialization. Coefficients and
  capacity curves are explicitly publishable under the vendor terms; raw rows are not.

## Invariants this task must not break

**Calibrated, not assumed.** This is the task that earns the phrase. No fallback constant, no prior
pinned to a literature value, no "if the fit looks wrong use 10 bps".

**No look-ahead.** The train/test split is by day and in time order: fit on the earlier day, test on
the later. A random split across days would let the model see the future, and with two days it would
also be indistinguishable from an in-sample fit.

**Determinism.** Same dataset, same coefficients.

**Honest limitations.** Test 6 and the regime split. A single headline coefficient across a range
where the exponent doubles is a summary that misleads, and this task's output should make that
difficult to write.

## Out of scope

- Serializing the fitted parameters — **M5-T3**.
- Using the model to size positions — **M7-T2** (OD-10).
- Funding-side modelling — **M6**.
- Changing the research symbols — **OD-3** is resolved to BTCUSDT/SOLUSDT.

## Open questions

**Q1 — weight observations, or treat every row equally?**
Recommendation: equal weights in the first pass, and look at the residuals before doing anything
cleverer. Weighting by size or by inverse variance is defensible and is also the kind of choice that
quietly determines which functional form wins.

**Q2 — fit per day and pool, or pool then fit?**
Recommendation: fit per day, report the spread, then pool. With two days the spread is the more
informative number: two coefficients that disagree sharply would say more about generalisation than
any single pooled R².

**Q3 — should the sliced-execution rows be fitted separately?**
Recommendation: yes, as a separate fit rather than a covariate. M4 measured that working an order
roughly halves large-order cost, so pooling the two schedules would fit a curve to a mixture and
describe neither.

## Implemented interface and decisions (2026-10-09)

`models/impact_model.py` provides `fit(frame, train_end=..., test_end=..., config=...)`,
`FittedLaw.predict(adv_fraction)` and the evidence-bound calibration loader. Training uses
the 90 calendar days strictly before the explicit cutoff; testing uses complete UTC days
in `[train_end, test_end)`. Each monthly walk-forward fold supplies its own fixed cutoffs.
Later partitions are not loaded for an earlier fold, and outside-fold rows do not enter
validation, coefficients, size bands or residuals. A group needs eligible training and
held-out days in a comparable depth regime; unavailable groups/regimes are recorded,
and a run with no evaluable square-root fit fails.

The Q1–Q3 starting choices are implemented: equal eligible row weights, pooled fits with
per-training-day coefficients and their spread, separate execution schedules. Symbols
and buy/sell directions are also separated. Every depth regime gets an all-size diagnostic
and three size bins by default. Bin boundaries are quantiles of unique training sizes,
not inferred liquidity breakpoints or boundaries learned from held-out data. ADV input
is a fraction (percent is fraction × 100). The coefficient's output unit is bps.

Square-root and linear models use least squares through the origin. The power diagnostic
uses log-space OLS on positive training targets, explicitly counts nonpositive exclusions,
and scores all eligible held-out targets in original bps. Signed slippage is retained:
sliced fills can benefit from price movement, and static fills can have tiny signed
rounding residuals. Negative fitted coefficients are reported without clipping; the sign
screen flags them as unusable for a nonnegative impact-cost law. This is a diagnostic,
not permission to apply negative transaction costs in M7. Constant-target R² is null
with an explicit reason; poor negative R² is preserved. No fallback coefficient is used.

The CLI verifies M5-T1 manifest identities, current input evidence and output hashes,
including stability during reading. It reads Parquet fragments directly so adjacent
manifest JSON and Hive/string type inference cannot corrupt loading. Reports contain
training/test dates and counts, exclusions, per-day fits, depth and size regimes,
extrapolation flags, and residuals versus predicted impact and normalized size.
`report.json`, `residuals.parquet` and residual plots stay under the ignored data root.
Dense residual rows/plots must not be treated as approved public vendor-data exports.
Depth/exhaustion flags are outcome diagnostics, not permission to select an entry model
using future slice outcomes. M7 must use decision-time observables when selecting a
cost regime. M5-T3 still owns a versioned deployable parameter format and loader.

Example, after BTC/SOL calibration partitions pass admission:

```bash
export PERPCARRY_DATA_ROOT="$PWD/data/btc-sol"
uv run python -m perpcarry.models.impact_model --symbol BTCUSDT --symbol SOLUSDT \
  --train-end 2025-10-01 --test-end 2025-11-01 --train-days 90
```

The command writes under `impact_fits/train-end=2025-10-01_test-end=2025-11-01/`.
Rerunning that fold replaces its report/residuals and removes obsolete residual figures;
avoid concurrent writers to the same destination. The actual BTC/SOL invocation currently
refuses missing calibration partitions. This task completes fitting machinery, not a
real-data coefficient, capacity or Sharpe claim.
