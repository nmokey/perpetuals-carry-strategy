# External Dependencies Audit

**Date:** 2026-08-12
**Scope:** Every assumption `design-doc.md` makes about an external service.
**Method:** Each claim was checked by actually calling the service or downloading the file from
this machine and this location. Nothing below is inferred from documentation — where a claim could
not be verified, it says so.

**Why this exists:** the design doc's remote assumptions were written from plausibility rather than
observation, and the first three that were checked all turned out to be wrong or blocked. This is
the sweep of the rest, done before implementation rather than during it.

---

## Summary

| # | Assumption (design doc) | Status | Impact |
|---|---|---|---|
| A1 | Trades with contiguous `trade_id` and aggressor side are freely available | **Holds** | — |
| A2 | L2 book snapshots + diffs with `update_id` are obtainable | **Was broken; now solved** | OD-2 |
| A3 | Funding history includes `mark_price` at settlement | **Broken** | §3.3, M1-T2, M7-T4 |
| A4 | Data comes from "the venue's public endpoints" (§4.1) | **Broken** | M1, M2, all live capture |
| A5 | A venue REST snapshot can validate book reconstruction (M2-T2) | **Broken; alternative found** | M2-T2, M2-T3 |
| A6 | "Venue-reported volume" is available for reconciliation (M1-T1) | **Holds via a different route** | M1-T1 |
| A7 | `trade_id` has no gaps (M1-T1) | **Holds only for one dataset** | M1-T1 |
| A8 | A "published funding calendar" exists to match against (M1-T2) | **No such artifact; derivable** | M1-T2 |
| A9 | A thin altcoin has usable public history (OD-3, M8-T2) | **Holds** | — |
| A10 | Historically accurate fee schedules are obtainable (OD-11) | **Gap — unresolved** | M7-T4, headline P&L |
| A11 | Symbol metadata (tick/step size) is available | **Not stated in the doc; broken; workaround verified** | M2, M4-T3, M7-T2 |
| A12 | "8h funding for most symbols" (OD-1) | **Measured; materially misleading** — 8h, 4h and 1h all occur, and vary within a symbol | M6, M7, M8 |
| A13 | Free ADV figures exist to unit-test against (M4-T3) | **No authoritative source; derivable** | M4-T3 |

Two items — **A10** (fees) and the storage cost noted under A2 — still need a decision. Everything
else either holds or has a verified path. A2's licensing question has since been resolved by
reading the terms; see A2.

---

## The core finding

The design doc assumes one venue can supply deep history *and* real order book data. From this
location, **no free source does** — but a combination does, and it preserves single-venue
integrity:

| Source | Trades | Funding | L2 book | Reachable |
|---|---|---|---|---|
| `data.binance.vision` (S3) | Years, current | Years, current | **None usable** | Yes |
| Binance REST / WS | — | — | Live L2 | **No — geo-blocked** |
| Bybit | — | — | — | **No — geo-blocked** |
| OKX REST / WS | Shallow | **~3 months only** | Live L2 with `seqId` | Yes |
| Tardis.dev free tier | 1st of month | 1st of month | **True L2, 1st of month, back to 2020** | Yes |

Tardis's free samples are for **`binance-futures`**, the same venue as the deep archive. So
Binance remains a single coherent venue for the whole project, with the book gap filled.

---

## Detail

### A1 — Trades. Holds.

`data.binance.vision/data/futures/um/daily/trades/{SYM}/` verified current through 2026-08-01.
Schema `id, price, qty, quote_qty, time, is_buyer_maker`. S3-backed, **not** geo-blocked.
920 symbols carry monthly `fundingRate`; thin symbols (`0GUSDT`, `1000BONKUSDT`) carry `trades`,
`bookDepth`, and `fundingRate` alike.

### A2 — L2 order book. Was broken; now solved.

**Broken as assumed.** OD-2 option (c), "top-of-book / partial-depth snapshots, free, immediately
available", does not exist:

- `bookDepth` is not an order book — cumulative depth at 12 fixed percentage bands (±0.2, ±1…5%)
  from mid, ~2,628 irregular samples/day, second-resolution timestamps, no `update_id`, no
  per-level prices. Cannot drive a book walk; cannot exercise the M2 replayer.
- `bookTicker` (L1) was **discontinued**: 2023-05-16 → 2024-03-30, 404 from 2024-04-01 onward.

**Solved.** Tardis publishes free samples with no API key: `incremental_book_L2` returns
`exchange, symbol, timestamp, local_timestamp, is_snapshot, side, price, amount`, where
`amount = 0` means the level was removed — matching §3.2 exactly, including its `0 = price level
removed` convention.

Coverage verified by probe: **first day of every month → HTTP 200; every other day → HTTP 401.**
Works back to at least 2020-01-01, for altcoins (`DOGEUSDT`) and other venues (`okex-swap`), and
across data types (`trades`, `quotes`, `book_snapshot_25`, `derivative_ticker`).

**Why 1 day/month is enough:** the architecture already decouples this. M5 calibrates an impact
*model* from book data; M7's backtest consumes the fitted model, not the raw book. Continuous book
coverage was never required — only enough book days to fit and out-of-sample-validate the model.
Twelve days a year across several years gives both cross-sectional and temporal variation.

**Open cost question:** one day of `BTCUSDT` L2 is **449 MB compressed** (measured). Twelve days
≈ 5.4 GB/year compressed, several times that decompressed. A decision is needed on how many
months to pull and whether to downsample on ingest.

**Licensing — read 2026-08-12.** The free samples fall under the vendor's standard Terms of
Service; there is no separate sample licence. "Permitted Use" covers *internal business, research,
educational or personal use*, so the project's core use is licensed. Clause 9.2(2) forbids
redistributing the Data, permitting only aggregated calculated Derived Data from which raw data
cannot be reconstructed. In practice: analysing locally and publishing fitted coefficients, capacity
curves and plots is fine; committing raw book rows, publishing them, or letting them reach a CI
cache is not — stricter than C9, and it rules out real vendor rows as test fixtures. One residual
ambiguity: publishing *research findings* is not expressly addressed, only redistribution of data.
Worth a confirmation email before M9. Full detail in `specs/M1/M1-T3`.

### A3 — `mark_price` in funding history. Broken.

§3.3 specifies `mark_price` "at funding settlement". The archive's schema is
`calc_time, funding_interval_hours, last_funding_rate` — no `symbol` (it is in the path), and **no
`mark_price`**. It does carry `funding_interval_hours`, which §3.3 does not model but the strategy
needs to annualise.

Also measured: settlement timestamps jitter by 1 ms (`...0000` vs `...0001`), so naive integer-hour
differencing reports a phantom 7-hour gap.

**Needs:** amend §3.3 to match reality — drop `mark_price`, add `funding_interval_hours` — or
specify a `markPriceKlines` join. Recommend the former; `mark_price` is unused until M7-T4.

### A4 — "the venue's public endpoints". Broken.

§4.1 assumes the ingestion layer pulls from public endpoints. From this location:

- `fapi.binance.com` — `"Service unavailable from a restricted location"` on `/fundingRate`,
  `/depth`, `/exchangeInfo`.
- `api.bybit.com` — CloudFront country block.
- `www.okx.com` — works.

The archive is S3 and unaffected. **Binance is the better source for history and an unavailable
one for live capture** — the opposite of what OD-2's option (a) assumes. Using a VPN to reach a
deliberately geo-blocked venue is a terms-of-service question, not a technical detail.

### A5 — Reference snapshot for book validation. Broken; alternative found.

M2-T2 says "matches reference checkpoints (e.g. venue REST snapshot)" and M2-T3 says "spot-check
against exchange UI/API". Both routes are geo-blocked.

**Alternative:** Tardis `book_snapshot_25` is on the same free tier (verified 200) and is
independently constructed from the same feed. Replaying `incremental_book_L2` and comparing the
top 25 levels against it is a stronger check than a manual UI spot-check, and it is automatable.
M2-T2/M2-T3 should be rewritten around it.

### A6 — Venue-reported volume. Holds via a different route.

`/fapi/v1/ticker/24hr` is geo-blocked, but `daily/klines/{SYM}/1m/` is in the archive (verified
200) and carries per-interval volume. Note the path has an **interval subdirectory** that the
naive pattern misses.

### A7 — `trade_id` gaps. **Broken — corrected 2026-08-20.**

The original finding said `trade_id` is contiguous in `trades` and only gapped in `aggTrades`
(where IDs are aggregation indices). **The first half is wrong.** Measured on the full
`0GUSDT` 2026-06 month: 154 gaps across 2,366,674 trades, 157 absent IDs, every run 1 or 2 long,
no duplicates, no time discontinuity.

The decisive test was the independent one: on 2026-06-01 (4 gaps) and 2026-06-15 (6 gaps) the
summed trade quantity still equals the summed 1m `klines` volume **exactly**. IDs are skipped;
trades are not lost. Contiguity is therefore not a property of this feed and never was — the
original probe simply did not look at enough data to see it.

Consequences, all applied: M1-T1's acceptance criterion is reworded (contiguity → no *runs* of
absent IDs beyond `fetch_trades.MAX_ID_SKIP`, with the klines equality carrying the real
completeness guarantee); `fetch_trades.backfill` classifies gaps instead of refusing any;
M1-T4's `trade_id_continuity` check does the same. `aggTrades` remains unusable for this purpose.

The general lesson is recorded as D-015: **an invariant confirmed on a sample is a hypothesis, not
a property** — and here the sample was one 200-row fixture and a few days.

### A8 — "Published funding calendar". No such artifact.

There is no machine-readable calendar to match against. It is derivable: expected settlements are
`funding_interval_hours` apart, and that column is in the data. The criterion should be reworded
to say so, with the ±ms tolerance from A3.

### A9 — Thin altcoin history. Holds.

920 symbols with `fundingRate`; thin names verified to carry `trades` and `bookDepth`. Tardis
free-tier L2 confirmed for `DOGEUSDT`. OD-3's deferral of symbol choice remains safe.

### A10 — Historical fee schedule. **Gap. Unresolved.**

OD-11 requires "the venue's historically accurate fee schedule … not current rates, if fees
changed over time". There is **no machine-readable source**: not in the archive, not in a
reachable API (`exchangeInfo` is geo-blocked), and `binance.com/en/fee/futureFee` returns HTTP 202
(a challenge page) rather than content.

This matters more than it looks. Taker fees on Binance USD-M are on the order of ~4 bp, against a
funding edge frequently in the same order of magnitude — the fee assumption can flip the sign of
the headline result.

**Options:** (a) source the schedule manually from documentation/archives and commit it as a dated
lookup table with citations; (b) treat the fee as a swept parameter and report the capacity answer
as a function of it, which is arguably more honest and turns a data gap into a sensitivity result;
(c) use a single documented current-rate assumption and state the limitation. **Recommend (b) with
(a) as the base case.** Needs a decision.

### A11 — Symbol metadata (tick size, step size). Not stated in the doc; broken; workaround verified.

The design doc never mentions needing it, but M2 (price-level granularity), M4-T3 (lot-size
normalisation) and M7-T2 (sizing) all do. `exchangeInfo` is geo-blocked; the archive has no
metadata tree (only `futures/`, `option/`, `spot/`); Tardis's instruments API requires a paid
subscription (`"available only for active pro and business subscriptions"`).

**Workaround verified:** infer from the trades archive by taking the GCD of distinct observed
prices and quantities. On `0GUSDT` this yields tick `0.0001`, step `1`, reproduced across three
disjoint days (2026-03-02, 2026-07-15, 2026-08-01) and on `ETHUSDT` (`0.01` / `0.001`).

> **Correction (same day).** An earlier draft of this section reported tick `0.01` for `0GUSDT`.
> That was wrong — a bug in the probe, which took the `min` of the observed decimal exponents
> rather than the `max`, truncating precision by 100×. The symbol trades at 4 decimal places.
> The lesson is C12's: the derivation must be tested against a known grid, since a wrong tick is a
> plausible number rather than an error.
Caveat: this recovers *observed* granularity, which equals the true tick only when enough distinct
prices occur — safe for a liquid symbol over a full day, less so for a thin one over a short
window. Should be computed once per symbol over a long window and committed as a lookup.

### A12 — "8h funding for most symbols". **Now measured, and materially misleading.**

Verified 2026-08-12 from the archive (June 2026): `BTCUSDT`, `ETHUSDT` and `DOGEUSDT` settle every
**8h** (90/month); `0GUSDT` and `1000BONKUSDT` settle every **4h** (180/month).

**And it is not even a per-symbol constant.** Checked again during M1-T2 against `0GUSDT`'s listing
month: it settled every **4h** from listing on 2025-09-17, switched to **1h** on 2025-09-22, and
was back to 4h by 2026-06. So the cadence varies *within* a symbol over time, and 1h occurs.

The doc's claim is true for majors and false for exactly the class of symbol this project sets out
to study (OD-3's thin altcoin, M8-T2). Hard-coding 8h would misstate a 1h symbol's annualised
funding by **8×**. `funding_interval_hours` is a per-row column — always read it, per row, not per
symbol.

This also lands on M6: an AR(1) fit over a window whose sampling frequency changes mid-way is not
sampling one process throughout. Tracked on the `blockers.md` watch list.

Two related findings from the same check:

- **Thin-symbol funding is an order of magnitude larger.** `0GUSDT` reached −23.9 bp in a single
  4h settlement against BTC's −0.67 bp per 8h. Six settlements a day at that scale is a much larger
  gross carry, which is exactly why execution cost decides whether it is real.
- **`1000BONKUSDT` is missing a settlement** — 179 where 180 are expected, an 8h gap after
  2026-06-24 00:00 UTC. A genuine upstream gap, and the first concrete case for M1-T4's allowlist.

### A13 — "Known ADV figures" for M4-T3. No authoritative source; derivable.

M4-T3 says "unit tested against known ADV figures for test symbol/date" without naming a source.
No free authoritative reference exists. Derive from `klines` volume and treat the derived value as
the fixture, documenting it as self-referential rather than independent.

---

## What needs to change in the design doc

1. **§3.3** — drop `mark_price`, add `funding_interval_hours`.
2. **§3.2** — keep as-is; Tardis `incremental_book_L2` matches it. Note the source explicitly.
3. **§4.1** — "public endpoints" → the archive + vendor samples; note the geo-block.
4. **OD-2** — rewrite the options against A2. Option (c) as written is not available; the free
   Tardis tier is a new option that meets the original criterion.
5. **OD-11** — record that no machine-readable historical fee schedule exists, and resolve A10.
6. **M1-T1** — name the `trades` dataset explicitly, or relax the `trade_id` criterion.
7. **M1-T2** — reword "published funding calendar" to the derived check, with tolerance.
8. **M2-T2 / M2-T3** — replace "venue REST snapshot" / "exchange UI" with Tardis
   `book_snapshot_25`.
9. **New task, M1** — symbol metadata derivation (A11). Currently specified nowhere.
10. **§10** — add the vendor dependency and the storage footprint.

## Recommendation

Resolve OD-2 as: **Binance USD-M throughout, with book data from the Tardis free tier
(first-of-month `incremental_book_L2`), validated against `book_snapshot_25`.** Single venue, deep
funding and trades history, true L2, no geo-block, no cost.

Then the remaining open item before implementation is **A10 (fees)**, which is a modelling
decision rather than a data-availability one.

**No live capture is needed, and nothing decays with time.** Every source above is a static
historical archive, so there is no recorder to run and no cost to deciding the remaining questions
carefully. An earlier draft of this document urged starting an OKX recorder immediately; that
advice was correct only while option (a) was still live, and is now withdrawn.

The one mild argument against indefinite delay is precedent rather than decay: `bookTicker` was
published from 2023-05 to 2024-03 and then simply stopped, and the vendor's free tier is a courtesy
rather than a contract. Pull the corpus once M1-T3 exists; there is no reason to rush it tonight.
