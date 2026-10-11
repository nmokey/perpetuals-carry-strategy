# M7-T3 — Chronological walk-forward integration

**Milestone:** M7
**Status:** Implemented and verified (2026-10-10)
**Depends on:** M7-T2/T4 implemented; OD-12 resolved (common monthly folds)
**Design doc:** Section 5, M7

## Goal and acceptance
Connect the actual M6 rolling model, T1 intents, T2 sizing and T4 cash accounting in a
chronological event loop, with `tools/run_backtest.py` for explicit local input manifests.

> Reproducible given fixed seed; "future data poisoning" test confirms no leakage

Tests run actual models and accounting, compare deterministic output exactly, poison
future funding/prices/evidence, withhold and reorder suffixes, and verify earlier records
are unchanged. Corrupt future payloads must not be read before earlier output is yielded.

## Contract and ordering
`iter_backtest(config, events, fees, executor)` consumes one chronological event at a time.
Funding events before the scored start only update the rolling model. The first scored
settlement must be the initial boundary and is accounted flat before any entry. At each
scored settlement, account actual mark-valued funding and then update the model; subsequent
market decisions predict strictly future settlements. Require one decision per settlement
at the configured delay (example: 16 seconds), outside T4's 15-second fill guard. Missing,
disabled or late decisions fail as encountered. This delay assumes the observation is
available; it does not certify actual historical publication/ingestion latency. No full-stream sorting, pre-validation,
future suffix fit, global random stream or last-row forced liquidation.

Market events carry contemporaneous execution mids and independent valuation marks.
Their optional `Opportunity` includes a prior impact curve, dated funding approval,
T2 market evidence and explicit perp half-spread, spot execution and expected financing
charges. Missing admission prevents entry; held positions still produce exit intents.
Actual execution is separate from intent. A failed or unsupported exit raises with the
position still held; never fabricate a flat state. Financing charges are explicit events.

Impact evidence is supplied per chronological monthly fold: its complete validation end
must precede the fold start, and the opportunity must identify the current fold. Sealed
M5 artifacts are produced by the existing calibration workflow using prior data; the
loop does not fit books it does not have. CLI admission additionally requires artifact
training inside the configured trailing window, including held-out validation: a 90-day
training window plus additional validation exceeds a 90-day total window and is rejected.
Use an artifact with a compatible prior training/validation split. Funding refits causally on each update.
Approval and calibration hashes appear in decision records. No real approval is invented.

## Execution and capital
`InferredExecutor` applies the admitted side-specific square-root impact and explicit
spread to current perp mid, and explicit hedge execution bps to current spot mid.
It is labeled inferred execution, not observed daily L2. `BookExecutor` uses caller-supplied
copied C++ Pipeline checkpoints for both markets at the event time; refuses crossed,
exhausted, partial or beyond-validated-depth fills. Core reconstruction and SPSC ownership
are unchanged. Paired full fills are required in this first loop; T4 can represent
partial/unequal legs, but T3 does not invent recovery for an unhedged partial execution.

Derive contemporaneous fee estimates from the same T4 schedule used for realized fills.
Spot estimates are normalized by spot/perp price ratio. Forecast fees/spreads are
reference-notional approximations; actual commissions use executed prices. Expected
financing is a caller-supplied horizon fraction; realized financing is charged separately.

Initial equity and a positive fixed derivative collateral fraction are explicit scenario
parameters. Entry sizing is bounded by cash needed for spot plus derivative collateral
and current costs; actual proposed fills are checked before accounting. Current reserve
shortfalls (cash plus marked derivative P&L below the required reserve) abort the run, without simulated liquidation. This conservative capital
envelope is not Binance maintenance-margin or liquidation replay. OD-4/B-010 stay open.

## Inputs, outputs and limitations
JSONL event manifests are read lazily. TOML run config declares symbol, warmup/start/end
exclusive, model settings, policy, seed, execution mode, initial capital and collateral
fraction. CLI supports inferred execution only; library callers may supply book snapshots.
Current BTC/SOL study has a verified constant 8-hour cadence. Other runs declare cadence;
each row must match it. Calendar/cadence changes fail explicitly pending a dated calendar
adapter, rather than forecasting a next boundary from a backward interval.

Yield per-event decisions/valuations with gross/net equity, funding, fees, execution and
financing costs, original horizon, settlements held and provenance. Warmup emits no
scored equity. Output header labels engineering scope; footer reports observed coverage,
whether positions remain open and whether the configured funding/decision/terminal
valuation coverage is complete. Completion requires a valuation at end-exclusive minus
one millisecond. It does not establish daily-close coverage for subsequent M8 returns.
The footer count is scored records, not raw book events processed. No forced closing fill, daily Sharpe, headline capacity or profitability
claim. M8 owns metrics/comparison; B-009–B-012 still gate BTC/SOL research runs.

For the common study use 2025-10-01–2026-10-01 exclusive with July–September warmup,
identical for BTC/SOL. Input gaps fail as encountered; earlier yielded records remain
available. A truncated input is visibly incomplete, not a shorter successful study.

## Verification
794 offline Python tests passed (ten network tests deselected), with 66 new T3 checks.
Actual M5 artifact loading, M6 predictions, T1 decisions, T2 sizes, T4 fees/accounting
and C++ Pipeline checkpoint execution are exercised. Deterministic output and poisoned,
withheld, shuffled and corrupt future suffixes are checked without eager reads. All 38
isolated injected faults caused named test failures. Lint/format and architecture checks
passed. Synthetic reconciliation verifies engineering, not BTC/SOL research profitability.
