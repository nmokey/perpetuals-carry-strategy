# M6-T3 — Rolling funding forecasts

**Milestone:** M6
**Status:** Complete (implementation and causal verification, 2026-10-10); predictive adequacy remains open
**Depends on:** M6-T2 implementation verified; predictive adequacy remains open (B-012)
**Design doc:** Section 5, M6

## Goal and acceptance
Produce a causal rolling posterior and distribution of cumulative future settlement funding.

> Unit test confirms no look-ahead: withholding/shuffling future data does not change historical outputs

Tests compare historical forecasts with withheld, shuffled and poisoned future rows; pin
rolling cutoff eviction against an independent batch fit; check cadence reset, timestamp
ordering, missing settlements, staleness, shared posterior draws and future shock propagation.

## Design
`RollingFundingModel.update(funding_time, funding_rate, interval_hours)` admits ONE observed
settlement at a time. Times are integer UTC epoch milliseconds. The caller must only submit
rates actually available at its decision time; exchange event time is not ingestion latency.
Updates are strictly increasing, spacing uses the later row's declared cadence (5s archive
jitter tolerance). Gaps/duplicates reject without altering state. Cadence changes reset the
training segment. Never mix symbols: one model instance per symbol.

`posterior(as_of=...)` refits the M6-T2 conjugate model from observed settlements in
`[as_of - rolling_days, as_of]`, conditional on the first retained rate; default as_of is the
latest observed time. Default rolling_days=90, min_settlements=30, explicit baseline prior.
No pair borrows its lag from outside the window. Reject predictions before the latest admitted
observation or after more than one cadence plus 5s without a new observation. Insufficient
history after reset is explicitly unavailable. Small-window refitting avoids unstable
subtracting of sufficient-statistic quadratics; no accumulating posterior double counting.

`predict_cumulative_funding(horizon, as_of=..., draws=4096, seed=603)` takes a positive integer
number of future settlements, not calendar days. Draw coefficients and innovation variance
jointly once per path, keep them fixed within that path, and recursively evolve rates with
fresh independent Gaussian shocks. Return fixed-notional funding fraction samples and
mean/median/intervals/probability above a generic fraction threshold. No phi clipping;
nonfinite simulations fail explicitly. A finite empirical sample mean is a Monte Carlo
summary, not a guarantee of theoretical moments for arbitrary long horizons.

## Data, causality and evaluation
The diagnostic command uses hash-admitted BTC/SOL funding, preserving the fixed study.
At each study settlement, predict BEFORE admitting that rate. Refitting occurs each
settlement. One-step intervals/log scores/PIT/tails use exact Student-t marginals. Compare
with a frozen fit using the same initially retained 90-day history (not T2's 92-day fit).
The frozen comparator resets to the first available posterior after a cadence change;
old-cadence forecasts are excluded from matching-cadence scores. Report predeclared
one-day (3) and one-week (21) cumulative horizons for current 8h cadence,
95% interval coverage, lower-tail misses and positive-probability Brier scores. These are
diagnostic horizons, not OD-9 strategy policy. Never change them to flatter study results.
Score only complete horizons entirely inside the study with matching observed cadence;
report incomplete endpoints and cadence exclusions. Scores overlap in time and are dependent.

Future evaluation values never enter the forecast loop before observation; retrospective
scoring is a separate pass. Training event times, row counts, seeds, prior, provenance,
monthly summaries and forecast records survive in ignored JSON/Markdown artifacts.
Repeat seeds intentionally provide common random numbers across decisions/horizons; they
are not independent draws over calendar time. Approximate probability Monte Carlo standard
error is reported. Prior sensitivity uses predeclared variance-scale and precision variants;
no variant is selected as the new default on study outcomes.

## Out of scope
M7 entry/exit, holding policy, costs, P&L and capacity. Model adequacy is tested, not presumed.
No download, C++ change, full-study prior tuning or strategy threshold is introduced.

## Verified result
517 offline tests pass, including 30 new T3 tests; 16 isolated mutations are caught. Repeated
real-data reports are byte-identical. No-look-ahead acceptance is met. Rolling nominal 95%
one-step coverage improves to 96.62% BTC/96.35% SOL, but weekly cumulative coverage is
73.77%/87.91%; B-012 remains open. See `docs/analysis/M6-T3-rolling-funding.md`.
