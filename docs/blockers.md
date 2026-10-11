# Blockers

Anything preventing a milestone task from starting or finishing, plus known defects in the design
doc that will cause trouble when their milestone comes up.

Each entry: what is blocked, what would unblock it, and whether there is a usable interim path.
Move entries to **Resolved** with a date rather than deleting them — the resolution is often the
more useful record.

---

## Active (updated 2026-10-11)

M7-T1–T4 engineering is complete and merged into main. M8 research runs remain gated.
See [current status](current-status.md) for timestamped acquisition/validation counts.
Earlier progress entries are historical, not current download instructions.

### B-009 — Sample-calibrated inferred execution needs validation

D-039 resolves the scope: continuous funding/prices with execution costs calibrated
strictly from completed prior monthly samples. Continuous daily L2 is excluded.
All 60 sample archives are converted and all 30 expected symbol-days have passing
replay reports. Refresh corpus quality, generate admitted BTC/SOL calibration rows,
and fit/validate prior-fold square-root models. Spread/spot hedge cost assumptions
and sparse-day/stress generalization remain required before capacity/net Sharpe claims.
Passed top-25 replay does not certify deep levels or exact venue execution timing.

### B-010 — Research marks, costs, capital and manifests remain incomplete

Funding, aligned spot/perp trade-price bars, futures-bar volume/ADV and mark-price bars
are acquired and validated under their contracts. D-040 removes full raw-trade coverage
as a requirement for the explicit active-study ADV route; rejected October 10 trade
archives remain rejected. Preserve the raw-trade default for other callers.

Exact funding-charge marks remain unverified. Minute mark-bar opens are candidate
proxies, not certified marks. Obtain authorized exports from an accessible source or
explicitly select a proxy with payment sensitivity; no proxy has been adopted. Implement
causal valuation adapters with explicit availability/staleness and daily equity coverage.
The terminal M7 coverage check alone does not support daily-return Sharpe.

Select historical fee/account tier, discounts, spot commission asset and execution-cost
treatment, capital/collateral policy and return denominator. The current fee reference is
an explicit sensitivity assumption. M7 quote-equivalent accounting and fixed collateral
scenarios are engineering implementations, not a historical venue wallet/liquidation model.
Freeze dated policy choices and assemble evidence-bound M7 manifests before M8 runs.

### B-011 — Historical executable contract rules remain unadmitted

An official notice announces SOL tick 0.001→0.01 before the study (2024-10-14). Rare
early executions off 0.01 explain the empirical GCD of 0.001; grandfathered orders are
a possible explanation, not proven. Traded granularity is distinct from accepted new-order
ticks. SOL’s 2025-04-02 minimum-amount notice is not independent proof of lot step or
minimum notional. BTC’s 100→50 USDT minimum-notional rollout starts 2026-04-14 06:30
UTC over approximately four hours, without a verified exact boundary. Establish dated
spot/perpetual filters and reconcile these gaps before sizing admission. Tardis metadata
requests returned 401/pro-business-required. See
[historical source evidence](analysis/historical-fees-contracts.md).

### B-012 — Funding predictive adequacy remains unestablished

M6 inference/causal rolling forecasts pass engineering tests. Rolling nominal 95%
one-step coverage is 96.62% BTC/96.35% SOL, but monthly/downside gaps and weak weekly
cumulative coverage (73.77%/87.91%) remain. Prior sensitivity does not certify horizon
probabilities. Assess horizon/downside calibration and defensible policy treatment before
admitting a reliable probability entry gate; do not tune toward target Sharpe/capacity.
See [rolling funding findings](analysis/M6-T3-rolling-funding.md). This gates research
interpretation, not implementation of forecast or configurable decision mechanics.

### B-004 — Binance's REST/WS API is geo-blocked from this location; Bybit too

**Blocks.** Any live capture or REST pull from Binance — most importantly M1-T3 option (a).
Does **not** block M1-T1 or M1-T2.

**Verified 2026-08-12.** `fapi.binance.com` returns `"Service unavailable from a restricted
location according to 'b. Eligibility'"` for `/fapi/v1/fundingRate` and `/fapi/v1/depth`. Bybit's
`api.bybit.com` returns a CloudFront country block. **OKX works** — `/api/v5/market/books` returns
L2 levels with a `seqId`, and its funding history endpoint responds normally.

`data.binance.vision` is S3-backed and **not** geo-blocked, so the historical archives (trades,
aggTrades, klines, fundingRate, bookDepth) remain fully available. The split matters: Binance is
the better source for *history* and an unavailable source for *live capture*, from this machine.

**Not a blocker in practice.** Nothing in scope needs the live API: OD-2 resolved to historical
archives, so M1-T3 no longer has an option (a). This stays Active as a standing constraint rather
than an open task — it is the reason no code may call a venue endpoint, and the reason this project
cannot be extended to live or paper trading from here without changing venue.

Using a VPN to reach a venue that has deliberately geo-blocked the user is a terms-of-service
question, not a technical workaround.

---

## Watch list (historical entries; current scope overrides acquisition plans)

**Historical pre-server audit (superseded by the BTC/SOL acquisition entry in `progress.md`) — supersedes the earlier costing claims below.** The current
checkout has no data corpus available to verify. Earlier session reports describe 11 `0GUSDT`
book days from October 2025 through August 2026, and trades for September 2025 and June–July 2026.
October's ingestion stopped at the trade-ID guard; a reported October 10 volume shortfall of
approximately 4.4% remains unresolved. Verify partitions and reconciliation on the data host
before resuming ingestion or claiming usable calibration days.

`0GUSDT` listed in September 2025; the earlier projection of 24 available book days and a full
24-month corpus is invalid. BTC/ETH totals below are extrapolations, not measured corpus totals,
and the stated ±50% is not a measured confidence interval. Re-measure the chosen server's disk
and representative busy days, including archive cache and temporary output, before a bulk pull.

A calibration day needs complete, quality-checked volume history strictly before that day;
same-day book/trades overlap alone is insufficient. June 1 lacked prior trades in the original
corpus. October 1 cannot have a full 30-day window for a symbol listed in mid-September. M5-T1
must reject incomplete configured ADV windows rather than silently averaging available days.

The six M4 aggregate size points motivate comparing functional forms, but establish neither a
winning model nor general regime boundaries. Fit conclusions remain M5-T2's deliverable.

Not blocking yet; will bite at the milestone named.

- **Monthly archives are not published until the month closes, and `backfill` is month-granular.**
  Verified 2026-08-20: `0GUSDT-trades-2026-08.zip` and `0GUSDT-fundingRate-2026-08.zip` both 404
  while the daily `trades` files exist through 2026-08-19 (the daily archive lags ~1 day). So the
  current month cannot enter the corpus through `fetch_trades.backfill` / `fetch_funding.backfill`
  at all, and the study window must end at the **last complete month** unless a daily backfill path
  is added.

  This is not cosmetic: the Tardis book *is* available for the first of the current month, so
  pulling "everything available" produces a corpus with book data outside the trades window —
  exactly what `validate_data`'s `book_within_trades_window` check fired on during the M1 pipeline
  exercise. Calibrating impact on a day the backtest has no execution data for is the failure that
  check exists to prevent.

  Options when this matters: end the window at the last complete month (simplest, loses up to a
  month), or add a daily fallback to `backfill` for the trailing partial month. Decide before the
  bulk pull, since it changes what "24 months" means.

- **The book size estimate in M1-T3 Q1 is roughly half the truth.** The spec's arithmetic assumes
  ~449 MB/day compressed for `BTCUSDT` `incremental_book_L2`. Measured 2026-08-20:
  **893 MB** for 2026-06-01, plus 84 MB for the matching `book_snapshot_25`. The 24-month plan is
  therefore ~23 GB for BTC book alone rather than the ~10.8 GB the spec budgets, before Parquet
  output and before ETH.

  Note also that **Tardis does not answer `HEAD`** — it returns 404 where `GET` returns 200 — so any
  sizing probe must use a streamed `GET` and read `content-length`. A `HEAD`-based estimate silently
  reports the book datasets as absent and undercounts the total by the largest term.

  **Re-costed 2026-08-30 against stored Parquet and actual free disk**, which is what the pull is
  really billed in — the 893 MB above is the compressed archive, and it lands as 544 MB of Parquet
  (161,057,093 rows at 3.5 bytes/row). Per unit, measured from partitions on disk:

  | | book day, incl. `book_snapshot_25` | trades/day |
  |---|---|---|
  | `0GUSDT` | 17 MB | 0.54 MB |
  | `BTCUSDT` | **652 MB** | ~21 MB |
  | `ETHUSDT` | not measured | ~38 MB |

  A 24-month window is 24 book days per symbol (the free tier serves the first of each month) and
  ~730 trade days:

  | symbol | book | trades | total |
  |---|---|---|---|
  | `0GUSDT` | 0.4 GB | 0.4 GB | **~0.8 GB** |
  | `BTCUSDT` | 15.6 GB | 15.3 GB | **~31 GB** |
  | `ETHUSDT` | ~12 GB (estimated) | 27.7 GB | **~40 GB** |

  **Free disk at the time of measuring: 15 GB.** So the binding decision is *which second symbol*,
  not how long the window is:

  - **Unblocking M5 is nearly free.** `0GUSDT`'s remaining 21 first-of-month book days cost ~0.4 GB
    and take the calibration set from 2 usable days to 24 — the difference between an out-of-sample
    R² on a sample of one and a claim that means something. The whole `0GUSDT` 24-month corpus is
    under a gigabyte.
  - **A second thin altcoin is ~1 GB** and fits trivially. `BTCUSDT` (~31 GB) and `ETHUSDT` (~40 GB)
    do not fit at all. That makes **OD-3** — symbol selection, which the design doc defers to M8 —
    a decision with a storage consequence that lands at M5, not M8.
  - Reclaimable now: `data/validation/` is ~2 GB of regenerable CSV exports and `data/.cache/` ~1.2
    GB of raw archives prunable after ingest, giving ~18 GB. Still short of BTC's full window,
    though BTC *book only* — calibrating on BTC while backtesting on a thin symbol — would fit.

  **Confidence.** The `0GUSDT` and `BTCUSDT` figures are measured from real partitions. The
  trades/day rates come from three daily archives per symbol and vary ~7x with volatility (7.8–56 MB
  for BTC), so treat them as ±50%. The `ETHUSDT` book figure is a guess: no ETH book day has ever
  been downloaded, and it is the single largest unmeasured term in the table.

- ~~**M4-T2's dependency edge is tighter than necessary.**~~ **Moot as of 2026-08-29:** M3-T2
  completed, so the edge is satisfied rather than merely bypassable, exactly as M2-T1's edge on
  M1-T4 was. The reasoning is kept because it was right and may recur: an edge drawn for the
  validate-against-real-data half of a criterion should not serialize the half that can be built
  against synthetic fixtures. No dependency edge in the doc currently blocks anything.

- ~~**M7-T4 is sequenced after M7-T3, but T3 needs it.**~~ **Resolved 2026-10-10 (D-036):**
  T4 depends on T1/T2 and precedes T3; the loop depends on accounting. Acceptance criteria
  and task IDs are unchanged. Accounting and T3 integration subsequently completed (2026-10-10).

- **Funding cadence is not a symbol constant, and M6 assumes it is.** `0GUSDT` ran 4h at listing
  (2025-09-17), 1h from 2025-09-22, and 4h again by 2026-06. An AR(1) fit over a window whose
  sampling frequency changes mid-way is not sampling one process throughout. M6-T2's spec should
  address this — resample to a common cadence, model in continuous time, or restrict the window —
  rather than discovering it at fit time.

- **The book is validated only 25 levels deep, and M4 walks deeper than that.** Demonstrated
  2026-08-29: deleting one real update at `0.3997` — well below the top of a ~1000-level
  `0GUSDT` book — left the replay wrong and the harness still passed, because no
  `book_snapshot_25` image describes that depth. The same experiment at the most-updated price
  (`0.4204`, top of book) produced 10 correctly-categorised mismatches, so the check itself
  works; its *reach* is the issue. By level count it constrains ~2.5% of the book.

  This bites at **M4-T1/T2**, whose whole purpose is walking deep into the book for large
  orders — exactly the region no reference constrains. There is no deeper vendor reference on
  the free tier, so the options are: accept it and caveat the large-order end of the capacity
  curve in M9; or cross-check deep levels against a different invariant (monotone prices, no
  duplicate levels, quantity sanity) which is weaker but not nothing. Decide when M4-T1 is
  specced, not at write-up time.

  **Decided 2026-08-30 when M4-T1 was specced (D-021):** the first option, but made per-fill rather
  than left to the writeup. Every simulated fill reports `levels_consumed` and
  `beyond_validated_depth`, so the approximation travels with the number into M5's dataset and M9's
  capacity curve instead of being described once. Capping the walk at level 25 was rejected: it
  makes large orders look *cheaper* than they are and bounds the capacity answer by an artifact of
  the reference data. The underlying gap is unchanged and stays on this list — this disclosed it,
  it did not close it.

- **M2-T2's real-data validation can never run in CI, in either tier.** The Tardis licence forbids
  book data reaching CI (M1-T3 Licence section, Clause 9.2(2)), so the comparison against
  `book_snapshot_25` — which is the *entire* correctness argument for the book, since §3.2 has no
  `update_id` — is a dated local run whose committed artifact is an aggregated JSON summary. That
  is a knowing exception to C10 ("a rigor claim CI does not run is a claim about the past"), and
  the usual escape hatch of moving it to the nightly tier does not apply: nightly is still CI.

  Mitigation, per D-018: CI runs the harness end to end against a **synthetic** events+reference
  pair with an injected defect, so the mechanism is continuously tested and only the input is
  manual. Re-run the real check whenever `OrderBook` or `BookReplayer` changes, and state the gap
  in the M9 writeup rather than letting a reviewer find it.

  **Widened 2026-08-29:** M3-T3's pipeline run is in the same category and is covered the same way
  — synthetic in CI, real run local and recorded in `docs/validation/`. Its checkpoint is a SHA-256
  of the final book's `dump_csv`, which is committable precisely because a digest exposes no levels.
  The re-run trigger now reads: whenever `OrderBook`, `BookReplayer`, `Pipeline` or the book
  rendering changes. Two local runs are currently the evidence base — `M2-T2-*.json` and
  `M3-T3-*.json` — and both name the commit that produced them.


- **The corpus cannot support M5-T2's out-of-sample criterion, and the ceiling is structural.**
  Measured 2026-08-30: `0GUSDT` has trades for 2026-06-01 → 07-31 and **3** book days (06-01, 07-01,
  08-01), of which **2** have both book and trades; `BTCUSDT` has one book day and no trades. So the
  calibration set is two symbol-days on one symbol.

  M5-T2's criterion asks for out-of-sample R². With two days the only split is fit-on-one,
  test-on-the-other — a genuine out-of-sample test across a month gap, and also a sample of one.
  M8's cross-symbol comparison is not reachable at all.

  **The ceiling is not a backlog item.** The Tardis free tier serves the *first day of each month*
  (OD-2), so book coverage is ~12 days per symbol per year however long a pull runs; a 24-month
  window yields at most 24 book days per symbol. That is the budget the entire calibration lives
  inside.

  Unblock: pull the remaining first-of-month book days for `0GUSDT`, and pick a second symbol with
  overlapping trades so M8 has something to compare. Read the two entries above first — the book
  size estimate is ~2x under, and the window's end date is still undecided. M5-T1 is buildable and
  correct against what exists; it is M5-T2's *claim* that is thin, and M5-T2's spec carries a test
  that fails loudly rather than reporting an in-sample R² in an out-of-sample field.

---

## Resolved

### B-008 — ThreadSanitizer was not wired into the build — **resolved 2026-08-29**

Resolved by M3-T2. A `PERPCARRY_SANITIZER` CMake option applies `-fsanitize=<name>` globally
(globally, because TSan must instrument the code a race is observed *from*, or it reports nothing
and looks clean), and a `sanitizer` CI job builds with `PERPCARRY_SANITIZER=thread` and runs the
`[spsc]`-tagged tests. Per-PR, not the nightly tier the design doc specifies and which still does
not exist — a rigor claim CI does not run is a claim about the past (C10), and the run costs ~4s.

**Verified to catch something, which is the part that matters.** Weakening the queue's
release/acquire pair to `relaxed` produces `WARNING: ThreadSanitizer: data race` and a non-zero
exit; clean exits zero. `TSAN_OPTIONS=halt_on_error=1` is set so a reported race fails the job even
if that run's assertions do not happen to notice it.


### B-007 — symbol tick/step size had no obtainable source — **resolved 2026-08-20**

Resolved by implementing M1-T5. `derive_symbol_meta.py` recovers the grid by GCD over observed
trades and commits it to `python/perpcarry/ingestion/symbol_meta.json`:

| Symbol | Tick | Step | Windows | Trades | Distinct prices |
|---|---|---|---|---|---|
| `0GUSDT` | `0.0001` | `1` | 2026-03-02, 2026-07-15, 2026-08-01 | 726,893 | 773 |
| `BTCUSDT` | `0.1` | `0.001` | same | 11,680,353 | 65,187 |
| `ETHUSDT` | `0.01` | `0.001` | same | 19,517,566 | 26,835 |

Distinct-price counts are the **union** across the three windows, not the sum of their per-window
counts — see the 2026-08-20 progress entry for why that distinction mattered.

Every `0GUSDT` and `ETHUSDT` figure reproduces the hand-verified table in the spec exactly —
tick, step, per-window distinct-price counts and trade counts. `BTCUSDT` is new here; it is the
symbol whose book data M2–M4 replays, and the design doc never listed its tick as a dependency
either.

The three consumers (M2 price-level granularity, M4-T3 lot normalisation, M7-T2 sizing) can now
read a committed value instead of deriving one ad hoc — which matters because a value that
silently changed between runs would make backtests irreproducible.

**The residual limitation is unchanged and is not closed by this.** The GCD recovers *observed*
granularity, which equals the true tick only when enough distinct values occurred; it can
overestimate on a thin window and can never underestimate. The code reports a `confident` flag and
refuses to commit a low-confidence estimate rather than returning a plausible wrong number. For
any thin symbol this still deserves an explicit caveat in the M9 writeup.

Two things this does **not** cover, both out of scope by the spec and both real: contract
multiplier and minimum notional (not derivable this way; M7-T2 will hit a second metadata gap),
and historical re-ticking (the table holds one current value per symbol; cross-window disagreement
is raised as an error rather than resolved by taking the finest value, precisely because a
disagreement may mean a re-tick rather than a thin window).

---

### B-006 — no machine-readable historical fee schedule — **resolved 2026-08-12, filed 2026-08-20**

Resolved by OD-11 on the same day it was raised, via the recommended path: **fee treated as a
swept parameter, with a manually-sourced dated base-case table** — option (b) with (a) as the base
case. Capacity is reported as a function of the fee rather than resting on one assumed number.

This entry sat in **Active** for eight days after its own resolution, still claiming to be "the
main open item before implementation". Recorded rather than quietly deleted, because the failure
mode is the point: resolving an OD does not close the blocker that motivated it, and this file is
read as steering at the start of a session. **When an OD is resolved, sweep the blockers that cite
it in the same pass.**

The underlying data gap is unchanged and still real — there is no API for historical fee schedules
even where the venue is reachable, and taker fees are of the same order as the funding edge, so
the base-case table's citations need to be dated and checkable when M7-T4 lands.

---

### B-002 — no C++-side Parquet reader was specified — **resolved 2026-08-20**

Resolved as **D-012**: Python reads the Parquet and feeds rows to the replayer across the pybind11
boundary. The C++ core gains no Arrow/Parquet dependency and no file I/O at all.

The gap was real — §2's diagram drew storage feeding the C++ core directly while §10 listed no
Arrow C++ dependency, and nothing would have failed until someone tried to write the read. The
resolution follows the pipeline-level-boundary rule (Risk R4) rather than adding a dependency:
the boundary is crossed once per replay batch, not per tick.

§2's diagram is updated to route the inbound edge through the Python layer, so the document no
longer implies a read path that will not be built.

---

### B-001 / B-005 — historical L2 order book data — **resolved 2026-08-12**

Resolved as OD-2 option (d): the Tardis.dev free tier serves `incremental_book_L2` for
`binance-futures` with no API key, first day of every month, back to at least 2020 — matching §3.2
including the `amount = 0` removal convention, on the same venue as the trades and funding archive.

The original framing is preserved because the resolution turned on it: option (c) as the design doc
described it **did not exist**. `bookDepth` is cumulative depth at 12 fixed percentage bands from
mid, ~30s irregular sampling, no sequence numbers; `bookTicker` (L1) was discontinued after
2024-03-30. Neither can drive a book walk, so "start with (c) to unblock M2" was never available.

**Nothing here decays with time.** Earlier notes in this file urged starting a live recorder
because a recording-based option loses a day of data for every day of delay. That urgency died
with the resolution: every source the project now uses is a static historical archive. See
`external-dependencies-audit.md` §A2.

Residual, tracked in `specs/M1/M1-T3`: how many months to pull (~449 MB/day for BTC, 10 MB for a
thin symbol), and the vendor's terms on publishing *derived findings* — permitted use covers the
research itself; redistribution of raw data does not.

---

### B-003 — book schema assumed diffs the data lacks — **resolved 2026-08-12**

§3.2 was rewritten around the vendor's real schema: gains `is_snapshot` and `local_timestamp`,
**drops `update_id`**, which this feed does not carry. Dropped-update detection is therefore
snapshot-comparison (M2-T2 against `book_snapshot_25`) rather than sequence-based — strictly
weaker, and the design doc now says so rather than implying a guarantee it cannot make.

**Outcome, 2026-08-29.** The substitute works, within a boundary now measured rather than guessed:
564,783 images match exactly across two symbols, and injecting a dropped update at the top of book
is caught within 10 images. Injecting one *below level 25* is not caught at all — the reference
cannot see there. So "strictly weaker" turned out to mean "blind below the top 25", which is a
sharper statement than the original entry could make, and it is the form that belongs in M9.
