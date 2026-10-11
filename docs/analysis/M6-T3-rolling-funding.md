# M6-T3 — Rolling funding forecasts (2026-10-10)

## Outcome
Causal rolling updates and cumulative funding distributions are implemented and verified.
Refitting improves aggregate one-step coverage versus a frozen fit, but weekly cumulative
forecasts remain undercalibrated. M6 engineering is implemented; B-012 scientific adequacy
remains open. These forecasts are not a validated strategy gate or a profitability result.

## Method and data
Study unchanged: 2025-10-01 through 2026-09-30, July–September warmup, BTCUSDT/SOLUSDT.
All 914 funding fragments match the existing funding-specific audit. Each symbol has
1,371 admitted settlements and 1,095 scored settlements, with constant 8-hour cadence.
No acquisition or C++ work was performed.

At each study settlement time, use only already observed rates from the previous 90 days,
refit the exact M6-T2 conjugate posterior, predict, then admit the current rate. Retained
history has 269–270 settlements (268–269 regression pairs) because actual timestamps have
small offsets. No observation outside the retained window supplies a lag. Default minimum
history is 30 settlements. Missing/duplicate/backdated updates reject; cadence changes
reset the model and require fresh same-cadence history; stale forecasts are unavailable.
The public API accepts one observed update at a time. Event-time availability is an explicit
assumption of this historical harness; actual ingestion delay is not inferred from timestamps.

One-step distributions use exact Student-t marginals. Cumulative forecasts use 4,096 recursive
posterior predictive paths, seed 603: one shared coefficient/variance draw per path, fresh
Gaussian shocks at every future step. Horizons are 3 and 21 settlements (one day/one week
at current cadence), chosen as diagnostics, not strategy holding rules. Funding sums use
fixed notional and exclude price P&L, costs and compounding. Phi is not clipped.

The frozen comparator uses the same initial 90-day retained history, rather than T2's
92-day warmup, so its numbers differ slightly from the T2 report. Seeds supply common
random numbers across decisions/horizons; interval and probability summaries are Monte
Carlo estimates. No horizon or prior was selected to improve study outcomes. Longer-horizon
moments under an unrestricted posterior are not guaranteed by finite sample summaries.

## Actual results
| Measure | BTCUSDT | SOLUSDT |
|---|---:|---:|
| Frozen one-step nominal 95% coverage | 90.14% | 83.20% |
| Rolling one-step nominal 95% coverage | **96.62%** | **96.35%** |
| Rolling one-step lower / upper misses | 31 / 6 | 32 / 8 |
| Rolling one-step positive-probability Brier | 0.1215 | 0.2002 |
| Frozen one-step positive-probability Brier | 0.1393 | 0.2065 |
| One-day cumulative nominal 95% coverage | **95.43%** | **96.61%** |
| One-day cumulative lower / upper misses | 39 / 11 | 36 / 1 |
| Weekly cumulative nominal 95% coverage | **73.77%** | **87.91%** |
| Weekly cumulative lower / upper misses | 159 / 123 | 83 / 47 |
| Weekly cumulative positive-probability Brier | 0.1812 | 0.2621 |

One-step scores cover 1,095 settlements per symbol with zero unavailable forecasts or
cadence exclusions. One-day scoring uses 1,093 complete horizons, excluding two final
endpoints. Weekly scoring uses 1,075, excluding 20. Overlapping horizons are dependent;
coverage percentages and Brier scores are descriptive, not independent significance tests.
A lower Brier score is better on the same event/horizon; different horizons have different
outcomes, so their scores are not directly interchangeable.

Improved one-step coverage does not resolve the model's weaknesses:

- Lower misses materially outnumber upper misses. SOL one-day upper misses are only one,
  despite 36 lower misses. Two-sided coverage masks asymmetry.
- February 2026 one-step coverage is 86.90% for both symbols despite year-wide overcoverage.
- BTC residual ACF remains 0.142 at lag two and 0.192 at lag three; SOL is 0.061 and 0.062.
  Rolling parameter adaptation does not erase higher-order dependence.
- SOL forecasts expect 222.83 settlements below -1 bp versus 133 observed, while expecting
  only 7.84 below -5 bps versus 11 observed and 3.27 below -10 bps versus five observed.
  The downside distribution is not simply uniformly too narrow or too wide.
- Weekly coverage falls far below nominal for both symbols. Plausible causes include
  residual dependence, changing parameters and non-Gaussian innovations; these checks
  do not isolate which explanation dominates. Broadly widening intervals is not validated
  as a repair.

Predeclared prior variants change one-step 95% coverage to 95.62–98.54% BTC and
96.16–96.99% SOL. These are sensitivity diagnostics, not a search for the best prior;
keep the original M6-T2 baseline. Weekly variant sensitivity was not evaluated. The sign
probability used in diagnostic Brier scoring does not define an entry threshold.

## Verification and reproduction
```bash
uv run python -m perpcarry.tools.evaluate_rolling_funding --config config/btc-sol-study.toml
```
Ignored outputs: `data/btc-sol/reports/rolling-funding/report.json` and `report.md`.
They retain forecast timestamps, training boundaries/counts, current posterior, exact
one-step distributions, cumulative summaries, monthly scores, priors, seeds, source/config/
audit hashes and versions. Forecast samples are available from the library API; the report
stores summaries. Retrospective scoring is a separate pass from forecasting.

Verified: 517 offline Python tests passed (30 new T3 tests), ten network tests deselected.
Sixteen isolated mutations caught, covering cutoff eviction/advance, resets, gaps, staleness,
recursive lags, cumulative sums, future shocks, shared path parameters, units, phi clipping,
nonfinite paths, horizon exclusions, current-settlement leakage and stale evidence.
Future withholding, shuffling, valid poisoning and a corrupt current/future rate leave prior
forecasts byte-for-byte unchanged; exact manual path replication checks the simulator.
Repeated real-data report bytes match. Ruff lint/format, architecture checks and whitespace
checks pass. No C++ changes or rerun; 85 C++ tests last passed during the organization audit.

## Current follow-up (2026-10-11)
M7-T1–T4 engineering is now complete, including configurable thresholds, fixed horizons,
sizing and accounting. Dated research parameters and treatment of B-012’s predictive
failures remain open; do not choose them from scored-year findings. D-039 selects
inferred execution from prior monthly samples; continuous daily books are excluded.
Actual impact fits, funding marks, fees, contract and capital admission still gate M8.
See [current status](../current-status.md). No strategy performance result is produced here.
