# Blockers

Anything preventing a milestone task from starting or finishing, plus known defects in the design
doc that will cause trouble when their milestone comes up.

Each entry: what is blocked, what would unblock it, and whether there is a usable interim path.
Move entries to **Resolved** with a date rather than deleting them — the resolution is often the
more useful record.

---

## Active

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

## Watch list

Not blocking yet; will bite at the milestone named.

- **M2-T1 / M4-T2 dependency edges are tighter than necessary.** M2-T1 (a pure data structure)
  is listed as depending on M1-T4 (full data QA), and M4-T2 on M3-T2 (the SPSC queue). Both can
  be developed and unit-tested against synthetic fixtures first; the dependency is real only for
  the validate-against-real-data half of each acceptance criterion. Don't let the doc's edge
  serialize work that could proceed in parallel.

- **M7-T4 is sequenced after M7-T3, but T3 needs it.** The backtest loop's P&L requires fee and
  funding settlement accounting. Expect to build a minimal settlement model inside T3 and refine
  it in T4, rather than treating T4 as purely additive.

- **Funding cadence is not a symbol constant, and M6 assumes it is.** `0GUSDT` ran 4h at listing
  (2025-09-17), 1h from 2025-09-22, and 4h again by 2026-06. An AR(1) fit over a window whose
  sampling frequency changes mid-way is not sampling one process throughout. M6-T2's spec should
  address this — resample to a common cadence, model in continuous time, or restrict the window —
  rather than discovering it at fit time.

- **ThreadSanitizer is not yet wired into the build.** M3-T2's acceptance criterion requires a
  TSan-clean stress run; there is currently no sanitizer build configuration, and no nightly CI
  tier to run it in (design doc Section 4.9 specifies the tier; it is not built).

---

## Resolved

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
