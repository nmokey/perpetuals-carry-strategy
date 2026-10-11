# M6-T2 — Bayesian AR(1)

**Milestone:** M6
**Status:** Implemented (2026-10-09); study predictive adequacy not cleared
**Depends on:** M6-T1 complete; OD-8 resolved (D-026)
**Design doc:** Section 5, M6

## Goal
Implement an exact conjugate funding regression with intercept, persistence and innovation
variance uncertainty. Check adequacy rather than force a favorable result.

## Acceptance criteria
> Recovers known true parameters within credible interval on synthetic AR(1) data; posterior predictive checks look reasonable on real data

Tests independently check conjugate algebra, known-parameter recovery, predictive uncertainty,
joint sampling, invalid inputs, constant inputs, explosive persistence and deterministic diagnostics.
Real-data checks must be reported even when they contradict adequacy; a failed scientific model
check is a finding, not a reason to manipulate data or priors.

## Design
Internally use basis points per settlement: y = intercept + phi * previous_y + Gaussian noise.
Condition on the first observation. Prior: sigma² ~ InvGamma(shape=3, scale=2 bps²),
(intercept_bps, phi)|sigma² ~ Normal((0,0), sigma² I). Thus E[sigma²]=1 bps²;
this is a proper explicit baseline prior, not empirically fitted or claimed noninformative.
Posterior precision = prior precision + X'X; posterior mean solves the normal equations.
Scale uses residual sum of squares plus the prior displacement quadratic (avoids cancellation).
Marginal coefficient and next-settlement predictive distributions are Student-t, df=2*shape;
predictive scale includes both parameter uncertainty and observation noise. Variance intervals
use inverse-gamma quantiles. Joint samples share one variance draw per coefficient vector.

`fit(rates, interval_hours, prior=Prior())` takes settlement fractions for ONE validated
constant-cadence segment. `Posterior.predict(previous_rates)` returns fraction-unit Student-t
parameters. `Posterior.summary()` explicitly labels bps/intercept, dimensionless phi and bps²
variance. No clipping/truncation of phi; report posterior mass outside |phi|<1. No stationary
long-run mean is assumed. No cadence mixing, resampling, or implicit time handling.

Checks: fit July–September warmup only, freeze posterior, evaluate October–September one step
conditional on the previous observed settlement (including final warmup settlement). This is
not a year-ahead open-loop forecast. In-sample posterior predictive replication uses fixed
observed lag inputs and shared parameter draws; its diagnostics are not independent validation.
Report interval coverage, PIT histogram, standardized residual lag correlation, tail frequencies,
log predictive score and replication checks of residual dispersion/tails/autocorrelation.
All diagnostics are exploratory and dependent in time; no trading threshold or tuned adequacy gate.

Reference for conjugate regression:
https://cforssen.gitlab.io/tif285-book/content/BayesianStatistics/BayesianLinearRegression/BayesianLinearRegression_ConjugatePrior.html

## Data and invariants
Use existing funding-specific audit hashes and strict loader for the configured common window.
Reject any cadence change in this command; M6-T3 will define causal reset/segment handling.
Store reproducible JSON/Markdown under ignored data root; synthetic tests contain no vendor data.
Fixed seeds, input/source/config hashes, versions and explicit boundaries accompany results.
Future study values do not affect warmup posterior. Fraction/bps conversion is explicit.

## Out of scope
M6-T3 rolling/online updates and cumulative multi-step forecasts; M7 entry/exit rules;
M5 impact fitting and all strategy returns/capacity. Prior sensitivity before strategy use remains
necessary; this task supplies a configurable prior and baseline checks, not an optimized prior.

## Open questions
Real-data adequacy is an empirical question. Negative tails, caps and higher-order dependence
may invalidate a Gaussian AR(1) even if synthetic recovery passes.

## Verification and acceptance status
25 new tests, 487 offline tests total; 13 isolated mutations caught. Real-data report is
byte-identical on repeated execution. Known-parameter recovery is met; warmup conditional
checks look plausible, but frozen study-year coverage underperforms nominal levels (BTC
90.05%, SOL 83.47% for 95% intervals). Scientific adequacy is not cleared. See
`docs/analysis/M6-T2-bayesian-funding.md`; M6-T3 rolling assessment can proceed without
certifying this model for strategy use.
