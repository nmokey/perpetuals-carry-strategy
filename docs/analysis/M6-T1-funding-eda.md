# M6-T1 — BTC/SOL funding findings

**Date:** 2026-10-09
**Status:** Complete; descriptive funding evidence, not strategy performance

Both BTCUSDT and SOLUSDT show positive serial dependence in funding, but their funding
distributions and stability differ. This provides real input for rolling Bayesian AR(1)
work. It does not establish that an AR(1) model is adequate or that funding carry survives
execution costs.

## Coverage and methods

For each symbol, 1,371 settlements cover 457 UTC days from 2025-07-01 through 2026-09-30.
The 92-day warmup contributes 276 settlements; the common 365-day study contributes
1,095. Both have an eight-hour cadence throughout the selected period, with no missing
days/settlements, duplicates, backwards timestamps or cadence changes detected.
Original millisecond settlement timestamps are retained, with the ingestion contract's
five-second spacing tolerance. All 914 selected Parquet fragments match the prior
funding-specific audit hashes; before/after checks also confirm stable reads.

ACF uses unadjusted direct covariances and Bartlett intervals; PACF uses Yule-Walker MLE
(`ywm`). Maximum lag is 24 settlements, or 192 hours at this cadence. Stationarity uses
intercept-only ADF with AIC lag selection (maximum 24) and intercept-only KPSS with
automatic bandwidth. Significance is 5%. Lag/window comparisons are exploratory and
not adjusted for multiple testing.

ADF tests a unit-root null, while KPSS tests a level-stationarity null. Non-rejection
does not prove either null. KPSS p-values outside the published table are reported as
bounds, rather than precise probabilities. These method choices follow the installed
statsmodels 0.14.6 APIs: [ADF](https://www.statsmodels.org/v0.14.6/generated/statsmodels.tsa.stattools.adfuller.html),
[KPSS](https://www.statsmodels.org/v0.14.6/generated/statsmodels.tsa.stattools.kpss.html),
[PACF](https://www.statsmodels.org/v0.14.6/generated/statsmodels.tsa.stattools.pacf.html).

## Study-period distributions

Rates below are **basis points per settlement**, not daily/annual returns. Positive
funding describes the short perpetual leg receiving funding under the funding convention.

| Metric | BTCUSDT | SOLUSDT |
|---|---:|---:|
| Settlements | 1,095 | 1,095 |
| Mean funding (bps) | 0.3081 | -0.1512 |
| Median funding (bps) | 0.3562 | 0.0617 |
| Standard deviation (bps) | 0.4662 | 1.6202 |
| Positive settlements | 76.44% | 53.06% |
| Negative settlements | 23.56% | 46.94% |
| Minimum funding (bps) | -1.5178 | -30.2761 |
| 1st percentile (bps) | -0.8799 | -4.7406 |
| 95th percentile (bps) | 1.0000 | 1.0000 |
| Longest observed positive streak (settlements) | 132 | 28 |
| ACF at one settlement lag | 0.6646 | 0.6691 |
| PACF at two settlement lags | 0.2666 | 0.0993 |
| Simple sum of settlement rates (%) | 3.374191 | -1.655464 |

The simple sums assume fixed notional and omit price changes, fees, spot-leg treatment,
execution costs and compounding. They are not trading returns, Sharpe or a capacity
answer. Positive streaks touching the window boundaries may be censored and do not
predict future streak duration.

BTC funding is positive more often and has a positive mean over this year. SOL has a
positive median and slightly more positive than negative settlements, but its negative
tail outweighs them in the mean. This is an empirical reason for predictive tail checks
before interpreting a persistence gate as an expected funding advantage. Frequent
observations at +1 bp are a distribution feature here; this report makes no inference
about an exchange cap.

## Stability and model implications

| Symbol/window | ADF p | KPSS p | Joint descriptive diagnostic |
|---|---:|---:|---|
| BTC warmup | 0.002669 | 0.01735 | Both nulls rejected; mixed |
| BTC study | 0.003377 | ≤0.01 | Both nulls rejected; mixed |
| SOL warmup | 2.387e-08 | ≥0.1 | Compatible with level stationarity |
| SOL study | 2.856e-18 | 0.03905 | Both nulls rejected; mixed |

The full-year mixed outcomes mean a globally stationary process should not simply be
assumed. Changing means, tails or other misspecification are possible explanations;
these tests do not identify a particular structural cause. BTC's nonzero higher-lag
PACF also makes it important to check AR(1) residual dependence, rather than relying
only on the strong lag-one ACF.

Twelve monthly cutoffs per symbol use **only the prior 90 completed UTC days**, each
with 270 settlements. The first cutoff is 2025-10-01 and the last is 2026-09-01.
Full-study statistics remain descriptive and must not tune historical priors,
thresholds or model orders.

| Prior monthly diagnostic | BTCUSDT windows | SOLUSDT windows |
|---|---:|---:|
| Compatible with level stationarity | 4 | 7 |
| Evidence against level stationarity | 5 | 0 |
| Mixed outcomes | 3 | 5 |

These counts are overlapping-window diagnostics, not independent successes/failures.
AR(1) remains the specified first model. M6-T2 should retain uncertainty, check
predictive tails and residual dependence, and report inadequacy if found. Rolling
updates and horizon forecasts belong to M6-T3; no Bayesian model or entry rule is
implemented by this report.

## Reproduction and artifacts

```bash
uv run python -m perpcarry.tools.analyze_funding --config config/btc-sol-study.toml
```

`--root` overrides the input root; otherwise an explicit `PERPCARRY_DATA_ROOT` takes
precedence over the study config. No data is downloaded. Funding-specific evidence is
required; overall trade/book coverage failures do not block this funding-only task.

Generated `report.json`, `report.md`, funding-history/distribution plots and warmup/study
ACF/PACF plots live under `data/btc-sol/reports/funding-eda/`. JSON preserves unrounded
statistics, all 24 prior windows, p-value bounds/warnings, input hashes and source/config
hashes. The reviewed narrative above is the publishable aggregate deliverable.
Environment: numpy 2.5.2, pandas 3.0.5, statsmodels 0.14.6.

Verification: 462 offline Python tests passed; 10 network tests deselected. Eleven
scratch-only defects were detected, including missing settlements, stale evidence,
lost read-stability checks, inclusive cutoffs, cadence pooling, wrong units/covariances,
substituted PACF, inverted test nulls, erased p-value bounds and zero-counting streaks.
Source changes are Python/docs only; existing C++ engineering is preserved.
