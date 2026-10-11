# BTC/SOL data options and research tradeoffs

Discussion record, **2026-10-08**. This records the considerations and alternatives discussed
after the server acquisition. It does **not** select a new execution mode, change the study
window or ADV source, authorize a purchase, or start a live collector.

The research symbols remain BTCUSDT/SOLUSDT. The intended common scored window remains
2025-10-01 through 2026-09-30, with July–September warmup and June volume prehistory.
See [the study plan](btc-sol-study.md) for the configuration, acquisition evidence and claims.

## What reconstructs an order book

Reconstruction needs a starting book state and an ordered, continuous stream of **book
updates**. A trade log records executions; it does not record every addition, cancellation
or quantity replacement at a price level. Therefore a beginning-of-month snapshot plus
that month's trades cannot recover the month's books.

For example, a snapshot contains 10 BTC offered at a price and a later trade executes 2 BTC.
The remaining quantity could be 8 BTC if nothing else changed, zero if the remainder was
canceled, or 28 BTC if another 20 BTC was added. All three histories can have the same trade
log and different executable liquidity. Subtracting executions alone is an assumed book
evolution, not reconstruction, and must not be presented as observed slippage.

[Binance's reconstruction procedure](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/websocket-market-streams/How-to-manage-a-local-order-book-correctly)
uses a snapshot and depth updates, checking update continuity and obtaining a new snapshot
after a gap. Our C++ reconstruction similarly advances book-update records; trade rows need
not be merged into that replay to reconstruct the book.

## What the first-of-month access actually contains

Tardis's free historical access covers the **entire first day of each month**, not one
snapshot followed by a month's updates. The relevant datasets are:

- `incremental_book_L2`: snapshot records and incremental level updates for that day.
- `book_snapshot_25`: repeated top-25 reference images for independent validation.

These support replay during the covered day. They do not supply updates for the remaining
days. Twelve first days cover 12/365 scored calendar days per symbol (3.29%); three additional
warmup days are candidates for prior calibration. Many events do not replace missing days.
Reference images independently constrain only the top 25 levels; deeper simulated fills
must retain their validation-depth caveat.

Two access issues are separate: regular-day requests returned **401** without historical
access; sampled-day downloads later returned **429** with an approximately 23-hour
Retry-After. Waiting addresses the rate limit, not the access restriction. Neither an
availability probe nor an authorized download guarantees complete, valid data.
[Tardis CSV documentation](https://docs.tardis.dev/downloadable-csv-files/overview.md)
describes first-day access and the separate update/snapshot datasets.

## Roles of the two data sources

| Research component | Inputs needed | Current source and consequence |
|---|---|---|
| Book reconstruction and sampled slippage | Book updates, initial state, validation references | Tardis alone can supply these; Binance trades are not needed to advance the book |
| Capacity in %ADV | Complete strictly prior volume history | Existing implementation uses Binance trades for 30-day ADV; one book day cannot supply the prior window |
| Rolling funding persistence | Continuous settled funding history | Downloaded Binance funding supports the Bayesian AR(1) research; a single book day is insufficient |
| Carry P&L and gross/net Sharpe | Funding, aligned spot/perp prices, costs, capital and fee assumptions | Binance funding/price histories are available; execution/accounting remain incomplete |
| Prospective collection | Live book changes, snapshots and accompanying market data | Tardis live software connects directly to the exchange from the collection host |

Both vendors are not inherently necessary for every experiment. An execution-only study
can use Tardis book data and report base quantities, notional and visible-depth fractions.
Reporting %ADV still needs prior volume. A carry study additionally needs continuous
funding/prices. Tardis offers other data types too, but coverage and access would have to
be established before replacing existing inputs; the downloaded Binance histories remain
useful under the sampled-book approaches.

The four validated trade days per symbol are pilots, not full ADV coverage. Both October
10 archives failed admission. Futures-bar volume is a possible alternative ADV input because
complete price bars have been downloaded, but adopting it is an **unresolved contract change**:
validate daily aggregation, units, UTC boundaries, volume quality and source disagreements,
then document the provenance and implications. Do not silently substitute it or conceal the
rejected trade days. The current generator still requires its existing trade-derived inputs.

## Options and what each can claim

| Option | What it can establish | Main requirements and tradeoffs |
|---|---|---|
| Full-year historical L2 replay | Book-based execution estimates throughout the fixed carry window | Obtain historical access for both symbols and adequate warmup; download/store/validate daily updates and references. Higher acquisition cost and processing load; coverage and depth limitations remain |
| Full-year carry backtest with sampled-book calibration | Continuous funding/price decisions with strictly prior regression-calibrated execution estimates | Validate several BTC/SOL book days and ADV; fit rolling square-root impact. Unobserved-day costs are inferred, with sparse regime coverage and uncertainty in net Sharpe/capacity |
| Sampled-day execution study | Direct reconstruction and static/sliced slippage measurements on admitted book days | Less data and a useful systems/calibration artifact. Does not establish continuous annual execution or annual carry Sharpe; conclusions are conditional on sampled days |
| Funding/price prototype with cost sensitivity | Funding-gate and accounting development; gross results and outcomes under declared cost scenarios | Can use downloaded continuous histories now. Assumed-cost scenarios are exploratory, not the final calibrated impact model or a verified net-capacity result |
| Prospective live collection | An owned dataset from collector startup onward | Run and monitor a collector continuously on an eligible host. Software/feed access can be free, but compute/storage/operations cost remains; cannot recover the chosen historical window or instantly supply a year |

The recommendation discussed was to combine sampled-day execution validation with a
continuous funding/price prototype, then consider sampled-book calibrated costs for a
clearly labeled model-based carry backtest. Checking full-year L2 access remains an option
if observed-book execution throughout the year is required. **No option has been selected**;
`execution.headline_coverage` remains `pending_user_choice`.

Even continuous historical replay is a counterfactual execution simulation: the historical
market did not observe our hypothetical orders. Preserve the sliced liquidity-depletion
and refresh approximation in D-023 rather than implying exact realized trading costs.

## Is one book day enough?

A full day can support an engineering/model pilot: reconstruct the book, generate many
size/time samples, fit the square-root relationship, and compare static versus sliced
execution. It cannot establish that coefficients generalize across symbols, months or
stress regimes. Observations within one day are correlated; sweeping many sizes against
one instant creates more rows, not more independent market regimes.

For a defensible progression:

1. Validate the whole book day against its references before calibration.
2. Fit on an earlier time block and test on a later block. Keep slices/sample horizons
   within their assigned block so future execution updates do not cross the split.
3. Test on later whole book days; use chronological splits and distinguish symbols,
   execution schedules, order-size regimes and independently validated depth.
4. Add ordinary and stress days where obtainable. First-of-month sampling can miss
   important regimes; uncertainty should reflect the number of days, not just fill rows.
5. For a continuous carry study, apply only coefficients fitted on completed prior days.
   Do not fit using all sampled months and then apply that fit to earlier decisions.

Multiple first-of-month days can support a credible **sampled-day impact study**, conditional
on validation and out-of-day performance. Annual carry requires continuous funding/price
accounting and must label unobserved execution costs. Do not concatenate isolated days as
one uninterrupted book, reset carry positions for convenience at each sampled day, or
annualize selected-day returns as though they covered the entire scored year.

## What free Tardis live streaming means

Tardis's live streaming software requires no API key and connects directly to exchange
WebSockets; it is not a hosted relay of Tardis's own captured live feed.
[Tardis live-streaming documentation](https://docs.tardis.dev/tardis-machine/streaming-real-time-data)
explains the local endpoint, normalized book changes/snapshots and reconnect handling.

Read-only reachability checks on this server on 2026-10-08 found a successful BTC/SOL depth
WebSocket upgrade (101), but Binance's REST book-snapshot request returned restricted-location
status 451. The handshake alone does not prove a healthy collector or a correctly initialized
book. Using Tardis's local software does not resolve the host's snapshot-access restriction;
an eligible collection host with access to both feeds is needed for this proposed path.

A production recorder would need durable timestamps/sequence information, rolling storage,
gap detection, reinitialization after gaps, automatic restart and alerts/storage monitoring.
No persistent collector has been started. Live capture is future coverage, separate from
paid access to already recorded history and from the fixed historical study.

## Current boundaries and unresolved choices

- No BTC/SOL book day has yet passed independent replay in the active research root.
  Completed 0G days support engineering tests, not BTC/SOL impact coefficients.
- Complete funding and minute price histories do not imply complete execution/ADV inputs.
  Exact trade-volume failures and SOL's historical grid disagreement remain recorded.
- Choose the headline scope: full-year replay, inferred costs, or a sampled-day execution
  deliverable alongside separate carry research. Do not silently shrink the common window.
- Decide the volume contract explicitly if using bar-derived ADV; retain quality gates.
- Fee tiers, spot execution assumptions, mark/index valuation and capital/collateral treatment
  still need specification before headline net returns.
- Preserve the C++ core and ingestion-to-consumer lock-free queue boundary under every option.
- 0.04% ADV / $210K capacity, 0.8 net Sharpe, 2.1 gross Sharpe and 400M+ processed events
  remain hypotheses. Do not count repeated replays/sweeps or synthetic events as unique
  source coverage, or treat a high event count as evidence of year-round generalization.
