# M7-T2 — Position sizing and modeled capacity

**Milestone:** M7
**Status:** Implemented and verified 2026-10-10; research evidence remains gated
**Depends on:** M7-T1 implemented; OD-10 engineering resolved by D-036
**Design doc:** Section 5, M7

## Goal and acceptance
Choose an executable short-perp quantity to maximize expected net funding dollars,
bounded by calibrated square-root marginal impact, the T1 probability gate and explicit
market/contract constraints. Report base quantity, notional and fraction of base ADV.

> Matches expected behavior on hand-constructed test cases

Tests independently calculate continuous and discrete optima, break-even capacity,
probability limits, lot rounding, min/max constraints, unsupported strata and chronology.
Synthetic fixtures use actual M5 fitting/export and M6/T1 interfaces. No BTC/SOL result
or preselected capacity figure is an input.

## Design
For x = quantity / base ADV, N = price * base ADV * x, let K be summed sell/open and
buy/close square-root coefficients converted from bps, b the sum of spread/fee/hedge/
financing fractions, and mu the expected cumulative funding fraction. Expected total
net dollars = N * (mu - b - K sqrt(x)). Marginal cost is b + 1.5 K sqrt(x), not the average
b + K sqrt(x). Continuous optimum x* = [(mu-b)/(1.5K)]^2 when K > 0 and mu > b.
Break-even x0 = [(mu-b)/K]^2 is different. No finite impact root exists when K = 0.

Only sizes inside the intersection of both sides' calibrated ranges and caller-declared
validated liquidity, maximum ADV fraction and maximum notional are considered. Neither
model nor current depth evidence supports unlimited capacity. Break-even roots outside
the calibration range are labeled below/above support, without publishing extrapolated
root values. An optimum clipped by coverage is not evidence of the true capacity.

Use a binary search over executable lot counts for the largest size passing the existing
T1 entry gate; it is monotone for nonnegative square-root costs. Compare the adjacent
executable lots around the bounded continuous optimum, including the zero alternative.
Choose smaller size on an exact profit tie. Never round up beyond a bound, reset the
holding horizon or bypass funding approval to generate sizes.

## Inputs and availability
`SizingInputs` carries symbol, contemporaneous price, strictly prior complete 30-day base
ADV and evidence digest, positive Decimal lot step, minimum quantity/notional, maximum
notional/ADV fraction, validated quantity bound, and dated contract metadata/digest.
Its ADV window ends at the decision day's UTC midnight; missing-day or unverifiable
volume must be rejected by the caller's corpus admission before constructing the record.
This is a pure decision API; it does not manufacture missing metadata or audit records.
A record expresses admitted evidence, not proof that a manually supplied hash is valid.

`costs.load_curve(...)` uses T1's stable artifact, known held-out cutoff, provenance and
supported stratum checks. `ExecutionCharges` explicitly supplies current spread, fee,
hedge and remaining financing assumptions. Terminal close costs use today's close law,
matching T1's stationary-cost approximation; future realized books are never used.
`size_position(...)` accepts the T1 strategy, scoped forecast/adequacy approval, curve,
charges and sizing inputs, and returns a size/diagnostics plus its T1 decision/cost quote.

## Invariants and scope
Deterministic, no future data, no flat fallback, no size extrapolation, no silent spot-cost
assumption, no unbounded-capacity claim. Decimal arithmetic enforces lot and monetary
bounds before costs/probability are evaluated. Both legs share the perp notional convention.
The supplied validated quantity cap must cover both entry and the modeled close envelope;
it is an explicit execution assumption, not a guarantee of future book depth.

Out of scope: corpus/contract/fee admission loaders, actual fills/capital/collateral,
price/hedge P&L, Sharpe and year backtests (T3/T4/M8). B-009–B-012 and OD-4 remain open.

## Output semantics and verification
Chosen quantity/notional/ADV, expected net dollars and marginal net fraction are separate
from the largest gate-admissible executable size and modeled break-even size. Both capacity
diagnostics have ADV and USDT-notional outputs. Break-even is published only within model
support; it can still exceed the probability or capital limit. `binding_limits` describes
the feasible maximum, not necessarily the chosen optimum. An unrepresentable break-even
notional is unavailable, never infinity.

55 new tests include six independent exhaustive executable-grid comparisons, hand-computed
marginal optima, rounding/minimum/maximum cases, probability caps, zero impact and no trade,
chronology/provenance and actual synthetic M5/M6/T1 integration. Full offline suite: 657
passed, ten network tests deselected; 26 isolated mutations caught. Ruff, architecture and
whitespace checks pass. No C++ or corpus changes; no BTC/SOL capacity or Sharpe measured.
