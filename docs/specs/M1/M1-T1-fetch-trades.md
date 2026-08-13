# M1-T1 — Historical trades downloader

**Milestone:** M1
**Status:** Draft
**Depends on:** M0-T4 (complete). OD-1 (venue) is OPEN with a documented default of Binance
Futures — this spec assumes that default; see Open questions.
**Design doc:** Section 3.1, Section 4.1, Section 5 (M1)

## Goal

Produce `fetch_trades.py`, which downloads historical perpetual-futures trades for a symbol and
date range and writes them as partitioned Parquet conforming to design doc Section 3.1. Trades
feed two downstream consumers: ADV normalisation for order sizing (M4-T3) and the volume profile
used by the time-sliced execution simulator (M4-T2).

## Data source

Binance USD-M futures public archive, `https://data.binance.vision/data/futures/um/`. **Verified
2026-08-12** by direct download.

This is an S3-backed static archive and is **not** geo-blocked, unlike the `fapi.binance.com`
REST API, which returns `"Service unavailable from a restricted location"` from the US (see
`blockers.md` B-004). The downloader must therefore use the archive exclusively — no REST
fallback, because there is no reachable REST to fall back to.

Two candidate datasets, both current through at least 2026-08-01:

| Dataset | Columns | Trade IDs |
|---|---|---|
| `trades/` | `id, price, qty, quote_qty, time, is_buyer_maker` | One row per trade; IDs contiguous |
| `aggTrades/` | `agg_trade_id, price, quantity, first_trade_id, last_trade_id, transact_time, is_buyer_maker` | Trades at the same price/side/ms collapsed into one row |

**Use `trades/`.** M1-T1's acceptance criterion is "no gaps in `trade_id` sequence", which only
holds literally for the raw dataset — see Open questions Q1. Files are correspondingly larger, so
the downloader streams and converts one day at a time rather than accumulating in memory.

Daily archives live at `daily/trades/{SYMBOL}/{SYMBOL}-trades-{YYYY-MM-DD}.zip`, monthly at
`monthly/trades/{SYMBOL}/{SYMBOL}-trades-{YYYY-MM}.zip`. Prefer monthly for backfill (fewer
requests) and daily for recent/incremental. Every archive has a sibling `.CHECKSUM` file — verify
it, since a truncated download is otherwise indistinguishable from a thin trading day.

## Schema mapping

Section 3.1 asks for `timestamp, trade_id, symbol, price, quantity, side`. Mapping from the
archive:

| Target | Source | Note |
|---|---|---|
| `timestamp` | `time` | int64 ms epoch |
| `trade_id` | `id` | int64 |
| `symbol` | *(from path)* | Not a column in the file; injected from the requested symbol |
| `price` | `price` | float64 |
| `quantity` | `qty` | float64, base asset units |
| `side` | derived from `is_buyer_maker` | **`is_buyer_maker == True` means the buyer was resting, so the aggressor was the seller → `side = "sell"`.** Inverted here silently flips every trade's sign downstream |

`side` is the aggressor side per Section 3.1. The inversion above is the single easiest thing to
get backwards in this task and has no loud failure mode, so it gets a dedicated test.

## Output

`data/trades/symbol={SYMBOL}/date={YYYY-MM-DD}/*.parquet`, via `perpcarry.storage.write_parquet`
with `partition_cols=["symbol", "date"]`.

Re-running a date must not duplicate rows — `write_parquet` defaults to `overwrite=True`
(`delete_matching`), which is what makes the fetch idempotent. Do not pass `overwrite=False`
without a deduplication step; that path appends (verified in `tests/test_storage.py`).

## Acceptance criteria

Copied verbatim from the design doc Section 5 table:

> Downloaded row counts consistent with venue-reported volume; no gaps in `trade_id` sequence

Expanded into checkable tests:

| # | Test | Where |
|---|---|---|
| 1 | `trade_id` is strictly increasing and contiguous within a day; a synthetic gap is detected and reported | `tests/ingestion/test_fetch_trades.py` |
| 2 | Aggressor side maps correctly: `is_buyer_maker=True → "sell"`, `False → "buy"` | same |
| 3 | Daily `quantity.sum()` reconciles with the same day's `klines` volume within a documented tolerance | same, marked `network` |
| 4 | Output conforms to the Section 3.1 schema — exact dtypes, no extra/missing columns | same |
| 5 | Re-fetching a date is idempotent — row count and content unchanged | same |
| 6 | `.CHECKSUM` mismatch raises rather than writing a partial day | same |
| 7 | A missing archive (404) for a date raises a clear error naming the date and URL | same |

Test 3 is the "consistent with venue-reported volume" half. `klines` carries a per-interval
volume field for the same symbol/day and is the natural cross-source check, since the REST
`/fapi/v1/ticker/24hr` endpoint is geo-blocked. Tolerance must be documented, not silently wide.

## Testing approach

Network tests are marked `@pytest.mark.network` and **deselected by default** (convention C10) —
CI must not depend on a live archive. Offline tests run against a small committed fixture: a few
hundred rows of real archive CSV, gzipped, well under any size concern. The fixture must be real
data, not synthesised, so schema drift in the upstream archive is caught.

## Out of scope

- Order book data — M1-T3.
- Funding rates — M1-T2.
- Cross-dataset QA and coverage reporting — M1-T4. This task validates only what it downloads.
- Any live/streaming ingestion. This is a historical backfill tool.

## Open questions

**Q1 — the acceptance criterion is venue-specific and needs a decision.** "No gaps in `trade_id`"
holds for the raw `trades` dataset but *not* for `aggTrades`, where IDs are aggregation indices and
gaps are expected by design. This spec resolves it by using `trades`. If the size of `trades`
proves impractical for the target date range, the criterion must be relaxed to monotonicity and
the design doc updated — do not switch datasets while leaving the criterion as written.

**Q2 — what date range?** Not specified anywhere. It is coupled to M1-T3: the impact model can
only be calibrated over the window where book data also exists, which is currently the binding
constraint (see M1-T3). Suggest deferring the trades backfill window until OD-2 is resolved, then
fetching trades for that window plus a lead-in for ADV.

**Q3 — OD-1 is still OPEN.** This spec assumes the documented default (Binance Futures). That
default is now materially better-supported than when written — the archive is reachable and
current from the US while the REST API is not — but the venue choice interacts with M1-T3, where
Binance is the *worse* option from this location. See B-004.
