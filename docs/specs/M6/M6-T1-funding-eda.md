# M6-T1 — Funding exploratory analysis

**Milestone:** M6
**Status:** Complete 2026-10-09; real BTC/SOL report generated and synthetic checks verified
**Depends on:** M1-T4 funding validation; independent of incomplete book/trade coverage
**Design doc:** Sections 4.6 and 5 (M6)

## Goal

Produce a reproducible report of BTC/SOL funding distributions, ACF/PACF and stationarity
checks over the common warmup/study windows. Separate descriptive study-wide evidence
from strictly prior monthly diagnostics that inform M6-T2/T3 validation.

## Acceptance criteria

Copied verbatim from the design doc:

> Documented notebook/report

| Criterion | Test |
|---|---|
| Funding inputs have complete UTC coverage, valid cadence and stable matching hashes | `tests/ingestion/test_funding_series.py` |
| ACF/PACF preserve settlement order, lag units and declared constant-cadence segments | `tests/models/test_funding_eda.py` |
| Stationarity tests report their opposing nulls, settings and clipped p-value bounds | same |
| Constant/short series are explicitly unavailable, not fabricated statistics | same |
| Monthly diagnostics use only completed settlements strictly before cutoff | same |
| Repeated analysis is deterministic; report JSON/Markdown and plots are produced | `tests/reporting/test_funding_eda_report.py` |

## Design and data

`ingestion/funding_series.py` reads explicit fragments and validates identity, dates,
finite rates, strictly increasing times, later-row interval spacing and endpoints.
The CLI additionally requires content matches to the existing funding-specific audit.
Models do not import CLI tools or replay. `models/funding_eda.py` owns calculations;
`reporting/funding_eda.py` owns report rendering; `tools/analyze_funding.py` owns config/I/O.

Rates remain raw settlement fractions; display uses bps (10,000 multiplier). Separate
contiguous cadence segments prevent unequal-interval lag pooling. No zero filling,
sorting, clipping or resampling repairs input defects. ACF uses direct unadjusted
covariances/Bartlett intervals; PACF uses Yule-Walker MLE (`ywm`). Maximum 24 lags is
predeclared and reduced for small samples. ADF uses intercept/AIC lag selection; KPSS
uses intercept/automatic bandwidth. Both use 5% significance; outcomes are exploratory,
uncorrected across multiple windows and never proofs of stationarity or AR(1) adequacy.

Warmup is July–September 2025; scored dates October 2025–September 2026. Twelve prior
monthly diagnostics use 90 calendar days with exclusive cutoffs. Full-year statistics
must not tune historical priors, thresholds or model orders. Positive runs use `rate > 0`
and carry boundary-censoring caveats. Simple rate sums describe hypothetical fixed
notional funding only; they are not strategy returns.

Generated JSON/Markdown/PNGs live under ignored `data/btc-sol/reports/funding-eda/`.
A reviewed aggregate narrative belongs in `docs/analysis/M6-T1-funding-eda.md`.
No book data, Bayesian posterior, entry gate, Sharpe or capacity is produced by this task.

## Methods

Check the installed statsmodels API/version; official references:
[ADF](https://www.statsmodels.org/v0.14.6/generated/statsmodels.tsa.stattools.adfuller.html),
[KPSS](https://www.statsmodels.org/v0.14.6/generated/statsmodels.tsa.stattools.kpss.html),
[PACF](https://www.statsmodels.org/v0.14.6/generated/statsmodels.tsa.stattools.pacf.html).
