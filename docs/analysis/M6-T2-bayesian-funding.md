# M6-T2 — Bayesian funding model checks (2026-10-09)

## Outcome
The exact Normal-Inverse-Gamma Gaussian AR(1) implementation is verified on synthetic
processes and the existing admitted BTC/SOL corpus. A frozen warmup fit does **not**
provide adequately calibrated study-year uncertainty. This is not a validated entry gate.

The design acceptance criterion's synthetic recovery component is met. Real predictive
adequacy remains unestablished; do not label the statistical model validated simply because
code tests pass. M6-T3 rolling evaluation is the next implementation task.

## Study and method
Existing window unchanged: July 1–September 30, 2025 warmup (276 settlements), October 1,
2025–September 30, 2026 study (1,095 settlements), each symbol at constant 8-hour cadence.
All 914 funding fragment hashes match the funding-specific audit. Funding observations
remain fractions per settlement; internal arithmetic uses basis points. No downloads.

Fit the 275 within-warmup pairs only. Freeze that posterior throughout the study, predicting
each next settlement conditional on the previous **observed** settlement, including the
last warmup settlement for the first study prediction. This is neither an open-loop annual
forecast nor a rolling model. Future poisoning leaves the warmup posterior and its
replication diagnostics unchanged. Rolling/online updates and cumulative horizons belong
exclusively to M6-T3.

Explicit baseline prior: coefficient mean (intercept, phi)=(0,0); conditional precision I;
innovation variance InvGamma(shape=3, scale=2 bps²), with prior mean 1 bps².
This is a proper baseline, not a noninformative or optimized prior. Posterior coefficient
and one-step marginals are Student-t and include variance/parameter uncertainty. Phi is
unrestricted; posterior mass outside |phi|<1 is reported rather than clipped. Prior sensitivity
must precede strategy use. Do not extrapolate a stationary long-run mean from the summary.
The formulas follow the [conjugate regression derivation](https://cforssen.gitlab.io/tif285-book/content/BayesianStatistics/BayesianLinearRegression/BayesianLinearRegression_ConjugatePrior.html).

## Actual findings
| Measure | BTCUSDT | SOLUSDT |
|---|---:|---:|
| Warmup phi, posterior mean | 0.5658 | 0.6122 |
| Phi 95% marginal interval | [0.4629, 0.6687] | [0.5169, 0.7075] |
| Intercept mean, bps/settlement | 0.2786 | 0.1684 |
| Innovation variance mean, bps² | 0.0891 | 0.2456 |
| Study nominal 50% coverage | 42.47% | 44.11% |
| Study nominal 80% coverage | 70.87% | 66.94% |
| Study nominal 95% coverage | **90.05%** | **83.47%** |
| Study nominal 99% coverage | 95.62% | 91.87% |
| Study residual std, bps | 0.3513 | 1.2077 |
| Worst study residual, bps | -1.6034 | -30.4632 |
| Study funding below -1 bps: observed / expected | 7 / 0.456 | 133 / 78.739 |
| Study funding below -5 bps: observed / expected | 0 / ~0 | 11 / 5.073 |
| Study funding below -10 bps: observed / expected | 0 / ~0 | 5 / 2.295 |

Both fitted warmup persistence coefficients are positive, but neither is a probability of
positive funding. Coverage falls below nominal levels, with particularly severe SOL
residual dispersion and downside surprises. BTC also retains residual dependence beyond
lag one (lag 3 ACF 0.200, lag 9 ACF 0.214); its lag-one residual ACF alone (-0.039) would
hide that. SOL lag-one residual ACF is near zero, yet uncertainty and tails remain wrong.
PIT first-decile counts are 261 BTC and 250 SOL versus 109.5 under uniform calibration;
these are exploratory counts, not independent significance tests.

In-sample conditional posterior replication at the fixed observed warmup lags, 2,000 shared
parameter/variance draws, seed 602, places observed residual dispersion, minimum and
lag-one ACF inside each replicated 95% interval. BTC residual ACF is near its lower edge
(-0.106 versus [-0.118, 0.111]). These warmup checks look plausible but do not establish
study validity. Replications are conditional, not free-running paths or independent holdout.

Parameter change, heteroskedasticity, non-Gaussian innovations, higher-order structure and
funding-distribution constraints are possible explanations; these checks do not distinguish
them. Causal rolling updates may help with change, but cannot be assumed to fix tail risk.
There is no revised prior, clipped observation, or extra fit chosen to improve these figures.

## Reproduction and validation
```bash
uv run python -m perpcarry.tools.check_funding_model --config config/btc-sol-study.toml
```
Ignored artifacts: `data/btc-sol/reports/funding-model/report.json` and `report.md`, including
prior/config, input and source hashes, package versions, PIT counts, residual ACFs,
variance intervals and predictive scores. Repeated real-data report bytes match exactly.
Log scores are densities in fraction units and are not economic returns or meaningful
without a comparable forecast benchmark.

Verified: 25 new offline tests; 487 total offline Python tests pass, 10 network tests
deselected; Ruff lint/format and whitespace checks pass. Thirteen isolated scratch
mutations are caught: units, prior precision/displacement, inverse-gamma shape,
predictive noise/parameter uncertainty, joint sampling, clipped phi, missing replication
noise, tail units, future leakage, mixed cadence and stale evidence. No C++ source changed;
85 C++ tests last passed during the preceding organization audit, not rerun for this task.
SciPy is now an explicit direct dependency; locking changes only the project's dependency
metadata, not installed package versions. No strategy P&L, Sharpe or capacity is produced.
