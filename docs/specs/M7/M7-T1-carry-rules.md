# M7-T1 — Carry entry and exit rules

**Milestone:** M7
**Status:** Implemented and verified 2026-10-10 (engineering; research admission gated)
**Depends on:** M5-T3 and M6-T3 implemented; OD-9 engineering policy resolved by D-035
**Design doc:** Section 5, M7

## Goal and acceptance
Implement `CarryStrategy` as a deterministic decision function for a candidate short-perp,
long-spot position, connecting cumulative funding uncertainty to admitted execution costs.

> Unit tests for each decision branch on synthetic inputs

Tests cover enter/wait/hold/exit, threshold equality, adverse-tail expected loss, remaining
horizon, sunk-cost exclusion, changed cadence, invalid/missing/stale/future inputs, symbol/
notional scope, forecast validation evidence, supported cost strata and bps conversion.

## Policy
OD-9 is resolved for configurable mechanics, not by choosing a headline parameter set.
`Policy(horizon_settlements, entry_probability, continuation_probability)` requires all
three explicitly, with 0 <= continuation < entry < 1. No default holding period or probability
is selected from M6's study-year findings. The design's 80% example is not an optimized value.
Choosing a dated parameter set using prior information remains a research/backtest gate.

Flat: enter only when P(cumulative funding > entry + terminal exit + financing costs)
strictly exceeds entry_probability AND the sample mean net funding is strictly positive.
The second condition prevents frequent small gains masking a disastrous negative tail.
Only short-perp/long-spot carry is supported; reverse carry needs borrow treatment later.

Open: the original planned settlement count remains fixed. Exit at horizon expiry, changed
cadence, unavailable/invalid inputs, rejected adequacy evidence, nonpositive expected
incremental edge or probability <= continuation_probability. Otherwise hold. Remaining
forecast horizon = original planned horizon - actual settlements already held, not a fresh
full horizon each decision. Compare holding to closing now using
future terminal close cost - immediate close cost + remaining financing. Entry execution
costs and already realized funding are sunk and never charged again in this comparison.

`decide(...)` returns an intent and reason, probability and mean edge where available.
It never mutates a position, executes/fills an order or claims closure when data is missing.
M7-T3/T4 will own actual fills, position state and settlement/P&L accounting.

## Admission and costs
Every research decision requires explicit, matching funding-adequacy evidence: symbol,
cadence, approved horizons, past validation cutoff, validity end, evidence digest and
matching model/configuration fingerprint. `funding.from_model(...)` wraps M6 predictions
with symbol plus a digest of inference sources, prior, rolling window and minimum history;
the digest remains stable as new observations arrive.
No approval is generated from M6's favorable aggregate coverage; B-012 is open. Synthetic
tests can explicitly use synthetic cost artifacts via a separate policy flag, default false.

`costs.from_artifact(...)` loads/hash-checks a strict M5 JSON artifact, uses square-root
sell-entry/buy-close laws with explicit schedule/size regime and caller-declared validated
order depth, rejects
negative/unsupported/extrapolated laws, and adds supplied spread/fee/hedge costs once.
All inputs and outputs are fractions of the same perp notional; bps are divided by 10,000.
Training AND held-out evidence end before the quote's decision time. This conservative
availability contract avoids using future artifact validation metadata. Actual file
generation date is reproducibility metadata, not a simulated trading clock.

The initial terminal close estimate equals the current buy-close quote, an explicit
stationary-cost approximation using currently known laws/spread/fees. The pure decision
interface also accepts a distinct future-close estimate known at decision time. Actual
future execution costs are never substituted into the gate. ADV/notional are already
admitted caller inputs; computing them and selecting capacity belongs to T2. Hedge costs
are explicit arguments, so no frictionless spot policy is silently selected (OD-4 open).

## Invariants and scope
Forecasts are regenerated at the decision time and must contain only known observations.
Future/expired cost or validation evidence cannot support an entry. Missing evidence keeps
flat positions flat and produces exit intent for held positions. No fallback impact cost,
uncalibrated probability approval, holding extension, future book lookup or claim target
is read. Tests and a scratch mutation audit run offline on synthetic inputs only.

Out of scope: M7-T2 sizing, M7-T3 backtest, M7-T4 accounting/fee table; empirically validated
probability thresholds; spot execution selection and continuous book coverage. No full
BTC/SOL trade signals or headline results until model/data/accounting gates are satisfied.

## Verification
85 strategy tests, including a synthetic artifact produced through real M5 fitting/export,
actual M6 rolling forecasts and M7 admission/decisions. Full offline suite: 602 passed,
ten network tests deselected. 22 isolated scratch mutations caught: equality boundaries,
expected losses, sunk-cost recharging, close-cost sign, horizon extension/expiry, scope/
time/adequacy admission, synthetic defaults, notional mismatch, artifact chronology,
bps units, trade side, depth/size extrapolation, stable reads and model-config binding.
Ruff, architecture and whitespace checks passed; C++ unchanged.
