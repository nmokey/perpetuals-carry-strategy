# BTC/SOL funding-rate carry study

## Scope and fixed window

Research symbols are **BTCUSDT and SOLUSDT**, Binance USD-M perpetuals. Existing `0GUSDT` data
and engineering validation remain useful for regression testing; its expansion stopped on
2026-10-08. It is not a research symbol or a substitute for BTC/SOL evidence.

| Period | UTC dates | Use |
|---|---|---|
| Volume prehistory | 2025-06-01 through 2025-06-30 | Strictly prior 30-day ADV for July calibration |
| Warm-up | 2025-07-01 through 2025-09-30 | Initial funding estimation and book-cost calibration; excluded from reported returns |
| Common scored window | **2025-10-01 through 2026-09-30** | Twelve chronological monthly out-of-sample folds, 365 calendar days |

This is the latest twelve complete calendar months as of 2026-10-08. The window is chosen by
calendar and common archive availability, not by Sharpe or capacity. Both symbols use identical
fold boundaries. Missing inputs fail the affected coverage criterion; do not shorten one symbol's
period or silently omit a bad day. Parameters are fitted on completed prior observations only.
The initial defaults are 90-day rolling funding estimation and monthly impact refits using a
90-day trailing calibration window. These are documented starting choices, not optimized results.
Any tuning is confined to warm-up or nested training folds, never the scored future fold.

Machine-readable settings and the separate hypothesis ledger are in `config/btc-sol-study.toml`.
The [data-options discussion record](btc-sol-data-options.md) explains reconstruction versus
trade replay, sampled-day evidence, inferred costs, and prospective live collection. These
alternatives have been logged; no new headline execution mode or ADV source is selected.
Active research data belongs in `data/btc-sol` via `PERPCARRY_DATA_ROOT`; existing test data stays
under the previous data root. Do not restart a `0GUSDT` bulk pull.

## Availability assessment before bulk acquisition

At the scope change, only BTC trades for 2026-07-01 were locally stored: 5,246,380 rows, exactly
reconciled against independent 1m kline volume. No SOL, BTC/SOL funding or BTC/SOL book corpus
was present. This is a local inventory, not evidence against remote coverage.

Streamed GET probes verified HTTP 200 and archive magic bytes for the following public archives
for both symbols across July 2025–September 2026: monthly trades, funding, futures/spot 1m bars,
and paired first-of-month L2 updates/top-25 snapshots. Ordinary October 2 L2 URLs return 401
without historical access. June trade and price archives also passed the availability probe for ADV prehistory (188 successful target probes in total).
The detailed, dated results are in `data/reports/btc-sol-availability.json`.

The initial 15-month probe measured approximately **21.09 GiB of compressed monthly trades** and
**14.76 GiB of compressed sampled books plus reference snapshots** across both symbols. This
excludes June prehistory, Parquet output, temporary exports and full daily L2. Sizes are measured
archive content lengths, not predictions of stored corpus size. The BTC pilot used about 1.65 GiB
peak RSS and produced 28.5 MiB Parquet for one day; it does not establish monthly peak memory.
Use bounded daily trade ingestion rather than materializing large BTC/SOL months in memory.

Sources checked on 2026-10-08:

- [Binance public archive documentation](https://github.com/binance/binance-public-data/blob/master/README.md): daily/monthly archives and checksums; spot timestamps since January 2025 are microseconds.
- [Tardis CSV quickstart](https://docs.tardis.dev/downloadable-csv-files/overview.md): first-of-month historical datasets require no API key.
- [Tardis CSV API](https://docs.tardis.dev/downloadable-csv-files/api.md): daily file semantics and ordered capture data.

An available archive can still contain holes. Downloads must pass checksums where published,
partition/date/ordering checks, trade-volume reconciliation and independent book replay before
being admitted to calibration or a scored fold.

## Verified acquisition and current defects (2026-10-08)

Both funding series cover all 457 warmup/study days: 1,371 settlements per symbol, constant 8-hour cadence, no gaps including month boundaries. Both markets for both symbols have complete June 2025–September 2026 minute grids (487 days per series), verified source checksums and output hashes. Reports are under `data/btc-sol/reports/`.

Four daily trade pilots per symbol passed exact reconciliation: June 1 and July 1, 2025; October 1, 2025; and September 1, 2026. This is still partial coverage, not complete ADV. The shared October 1 pilots contain: BTC 3,495,797 rows / 172,989.429 base units, SOL 3,097,739 rows / 24,943,731.13 units. October 10 failed for both: BTC trades understate kline volume by **6.59%** (18,810 large ID gaps); SOL by **6.75%** (19,874 large gaps). Neither day entered accepted partitions. These are daily-archive diagnostics; monthly equivalence has not been established for BTC/SOL. Keep the window fixed and investigate recovery/alternative volume evidence before asserting complete ADV coverage. No tolerance or allowlist was added.

BTC inferred tick/step agree on July 1 and October 1, 2025 and September 1, 2026 (0.1 / 0.001). SOL tick estimates disagree (0.001 early, 0.01 late; quantity step 0.01 throughout), so no timeless SOL metadata record was accepted. Historical grid regimes and the transition date need verification. This is an observed change in traded granularity, not yet a verified exchange change timestamp.

Sampled warmup book downloads currently return **429**, with a Retry-After of approximately 23 hours. Respect that cooldown; ordinary-day 401 access restrictions are a separate issue. No new BTC/SOL day has passed full independent book replay in the active research root yet. The overall corpus quality report remains failed on trade/funding window and continuity coverage because only four trade days per symbol are admitted; healthy individual funding/price series do not make the complete study eligible.

## What first-of-month books support

These are **full-day incremental L2 feeds** on the first of each month, paired with frequent
top-25 reference images. They are not twelve isolated book snapshots. Nevertheless, there are only
12 observed execution days per symbol in the scored year: **3.29% of its calendar days**.
Warm-up adds three book days per symbol. Row count can be large while calendar coverage remains
sparse; many correlated fills from a day do not create additional independent days.

They support C++ reconstruction/queue validation and a regression-calibrated square-root impact
model on sampled days, with chronological held-out diagnostics. They do **not** establish actual
spread, depth, impact decay or fill prices on the remaining 353 study days per symbol. Do not
carry an old book forward, interpolate it into missing days, or fit a whole-year coefficient and
apply it to earlier decisions.

Two execution-coverage choices are explicitly distinct; the headline choice is pending:

1. **Daily L2 execution replay.** Requires incremental L2 and matching validation references for
   all 365 study days per symbol, plus enough warm-up book history for initial calibration.
   Ordered snapshots/diffs, reconnect handling, and decision-time prices must be available.
   The free sampled archives alone are insufficient. Obtain access covering the entire window
   and warm-up; do not purchase or assume access silently.
2. **Continuous funding/price backtest with inferred costs.** Public continuous trades/bars and
   funding can drive daily decisions/valuation, while strictly prior sampled books calibrate
   the cost law. Report inferred execution on unobserved days, sparse calibration uncertainty,
   spread assumptions and stress sensitivity. This is a model-based backtest, not continuous
   observed-book replay. A sample-day-only study cannot be advertised as a full-year backtest.

The user is deciding which should headline the research. Public funding, prices, metadata,
trades and sampled book validation can proceed without prejudging that choice.

## Engineering and model requirements

- Preserve the C++ deterministic book core, sliced liquidity depletion, and SPSC queue. Research
  replay must pass producer events through that queue before cost simulation reads consumer state.
  Queue occupancy and scheduling must never influence fills or strategy decisions. Batch crossings
  avoid per-event Python/C++ calls. Distinguish real processing counts from isolated queue throughput.
- Primary impact law is a **regression-calibrated square-root** relationship to `quantity / ADV`.
  Fit touch-relative impact; account for the spread separately. Keep linear fits as diagnostics,
  not a replacement for the requested primary law. Report fit failures rather than use a forced
  coefficient. Separate symbols, execution schedules, and fills inside/beyond validated depth.
- Entry is gated by a **rolling Bayesian AR(1) funding-persistence posterior**. Closed-form
  Normal-Inverse-Gamma estimation is the initial method. Use only settled/available past funding;
  validate the actual cadence, and specify causal resampling or segmentation when it changes.
  Holding horizon, posterior probability threshold, priors, and exit rules still need M6/M7 specs.
- Report capacity in **% of trailing 30-day ADV** and **USDT notional at a stated contemporaneous
  reference price**, with the date/symbol and fee assumptions. ADV excludes the decision day.
- Report gross and net-of-cost Sharpe from the **same daily UTC return series and capital basis**,
  including inactive days, annualized by `sqrt(365)` with zero risk-free rate for this first pass.
  Define invested spot capital, perp collateral/leverage and valuation before computing returns.
  Include funding cash flows and hedged spot/perp price P&L; distinguish mark-price assumptions.
  Net means subtracting explicitly enumerated fees and modeled execution costs. A frictionless
  spot leg must be labeled and accompanied by a spot-cost sensitivity, not hidden in “net”.

## Coverage checklist and work needed

1. **Completed:** validate continuous funding for July 2025–September 2026, including cadence and month boundaries; retain the hash-bound audit when inputs change.
2. Acquire continuous BTC/SOL trades from June 2025–September 2026, or explicitly decide whether
   bar-derived volume replaces the existing trade-derived ADV contract. Do not silently substitute
   klines for trades. Reconcile every accepted trade day against independent volume and investigate
   the October 2025 stress period for both symbols.
3. **Acquisition completed:** aligned futures and spot 1m prices for June 2025–September 2026,
   with spot/futures timestamp normalization and availability after bar close. Identify mark/index
   and any liquidation assumptions before the cash-flow backtest is claimed complete.
4. Derive and review SOL tick/step metadata across disjoint historical windows; audit BTC metadata
   against the study period and log re-ticks rather than choosing the finest grid. Contract/minimum
   notional constraints remain a separate metadata requirement for executable sizing.
5. Validate sampled BTC/SOL L2 against its references. For daily replay, acquire the missing regular
   days too; for inferred costs, add stress/ordinary-day book coverage if obtainable to test whether
   monthly calibration transfers. Independent references constrain only 25 levels in either mode.
6. M5-T1/T2 dataset generation and fitting machinery are implemented; validate BTC/SOL data before producing research fits. Finish M5-T3 serialization, M6 Bayesian persistence, and M7 accounting/walk-forward tests. Completed M0–M4 engineering is retained.

## Claims to test

| Claim | Required evidence |
|---|---|
| 0.04% ADV / $210K capacity | Empirical zero-net-edge boundary, consistent symbol/date/price/ADV; report uncertainty and fee sensitivity |
| 0.8 net Sharpe | Full common-period net return series with costs, capital and missing-data policy specified |
| 2.1 gross Sharpe | Same decisions/positions, dates and capital denominator as net Sharpe, with costs removed |
| 400M+ processed events | Manifest of unique source records actually processed through the research pipeline, grouped by symbol/day/type |

These are **hypotheses, not implemented results, success criteria, test fixtures or tuning targets**.
0.04% ADV is a fraction of 0.0004; pairing it with $210K implies $525M ADV notional at that
reference price. Test that consistency rather than setting position size to $210K. For event counts,
report book updates, trades and reference rows separately; exclude repeat replays, synthetic stress
events and size-sweep repetitions from the unique-source total. Negative or lower results are valid.
