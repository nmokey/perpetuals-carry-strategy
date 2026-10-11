# Current BTC/SOL study status

Updated 2026-10-11. This is the current readiness summary; dated progress, analysis
and audit entries describe what was known when they were written.

## Scope and implementation

BTCUSDT/SOLUSDT share the scored UTC window 2025-10-01–2026-09-30, with
July–September warmup and June volume prehistory. D-039 selects a full-year
funding/price backtest with costs inferred from completed prior monthly book samples.
Continuous daily L2 acquisition is excluded. D-040 selects exact futures-bar base
volume and strictly prior 30-completed-day ADV; full raw-trade backfill is not required.
The raw-trade implementation default and rejected October 10 archives remain intact.
0G expansion is stopped; retain existing data for engineering tests.

M0–M4 engineering is complete. M5 calibration/fitting/serialization and M6 funding
analysis/inference/rolling forecasts are implemented. M7-T1–T4 engineering is complete,
including accounting and chronological backtesting. M8 research runs and M9 reporting
have not started. The nine task commits were merged into local and remote main at
`46baf50`; this refresh is a separate documentation task.

## Verified coverage snapshot

| Input | Current evidence |
|---|---|
| Funding | 457 days / 1,371 settlements per symbol; constant eight-hour cadence |
| Spot/perpetual trade-price bars | 487 complete days per series, June 2025–September 2026 |
| Futures-bar volume / ADV | 487 daily volumes and 457 strictly prior daily ADV windows per symbol |
| Mark-price bars | 457 complete days per symbol; both June 2026 omissions repaired with independently checksummed daily archives |
| Monthly sampled books | 60/60 archives structurally converted; acquisition complete |
| Independent book replay | 30/30 expected symbol-days have passing replay reports |

Book acquisition status was last updated at `2026-10-11T11:15:55.920194+00:00`; replay status
at `2026-10-11T11:17:39.580509+00:00`. Both workers have exited. Acquisition reports complete; the validator’s final status
is `waiting_acquisition` because it detected the exited acquisition process. Its
completed list nevertheless covers all 30 expected symbol-days, each with a passing
report. No missing sample day is inferred from that terminal worker status.
These are timestamped snapshots, not live counters. Read ignored
`data/btc-sol/reports/monthly-book-acquisition.json` and
`monthly-book-validation.json` for newer progress.

The passing replay reports cover 2,310,540,096 update events and 51,694,674 reference
images. Counts are standalone C++ replay counts, not queue/calibration throughput or
year-round book coverage. Top-25 comparison does not certify deeper levels or venue
execution timing. No real BTC/SOL impact fit or research performance result exists yet.

## Remaining work before M8 results

1. With sample acquisition/replay complete, refresh hash-bound corpus quality evidence,
   then generate actual BTC/SOL calibration datasets and prior-fold
   impact fits. Validate sparse-day generalization, spread and spot execution assumptions.
2. Obtain exact funding-charge marks, or explicitly choose and document a proxy with
   payment sensitivity. Minute mark-bar opens are candidates, not certified settlements.
   Implement causal valuation adapters with explicit availability/staleness and daily
   equity coverage; the existing terminal coverage check is not a daily-return series.
3. Establish dated spot/perpetual tick, quantity and minimum-notional rules, fees and
   commission-asset treatment. Historical SOL accepted-order ticks and BTC rollout
   timing remain unadmitted. Select capital/collateral and return-denominator policy.
4. Address funding predictive adequacy, especially longer-horizon/downside calibration,
   before approving probability-based entries. Working forecasts alone do not clear B-012.
5. Freeze dated research parameters, assemble chronological evidence-bound manifests,
   then implement/run M8-T1/T2, sensitivity sweeps and the naive-cost comparison.

Real-data impact calibration can now proceed once its fresh book-quality and
bar-ADV admission checks pass. Do not bypass
those checks because an inventory lists a day. See [blockers](blockers.md) and the
[workflow](server-workflow.md). No new scope or research policy is selected here.

## Verification and limits

Before publication of `46baf50`, 835 offline Python tests and 85 C++ tests passed;
ten network tests were deselected, and Ruff lint/format passed. These are recorded
engineering checks, not model adequacy or hosted-CI certification. This refresh changes
only Markdown. The capacity, Sharpe and 400M-event hypotheses remain claims to test;
no observed result is forced to match them. Raw data and operational workers stay local.
