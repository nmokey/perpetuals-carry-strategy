# M1-T1 — Historical trades downloader

**Milestone:** M1
**Status:** **Complete** (2026-08-12)
**Depends on:** M0-T4 (complete), M0-T6 (HTTP client — blocks this task).
OD-1 **resolved**: Binance USD-M futures.
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

Copied verbatim from the design doc Section 5 table (revised 2026-08-12):

> Daily summed quantity equals the same day's `klines` volume **exactly**; `trade_id` contiguous
> within and across days

Expanded into checkable tests:

| # | Test | Where |
|---|---|---|
| 1 | `trade_id` is strictly increasing and contiguous within a day; a synthetic gap is detected and reported | `tests/ingestion/test_fetch_trades.py` |
| 2 | Aggressor side maps correctly: `is_buyer_maker=True → "sell"`, `False → "buy"` | same |
| 3 | Daily summed quantity equals the same day's `klines` volume exactly, summed as `Decimal` | same, marked `network` |
| 4 | Output conforms to the Section 3.1 schema — exact dtypes, no extra/missing columns | same |
| 5 | Re-fetching a date is idempotent — row count and content unchanged | same |
| 6 | `.CHECKSUM` mismatch raises rather than writing a partial day | same |
| 7 | A missing archive (404) for a date raises a clear error naming the date and URL | same |

Test 3 is the "consistent with venue-reported volume" half. `klines` carries a per-interval
volume field for the same symbol/day and is the natural cross-source check, since the REST
`/fapi/v1/ticker/24hr` endpoint is geo-blocked. It is an **equality, not a tolerance** — measured
zero difference across three symbols; see `M1-T4-validate-data.md` Q1 for the numbers.

## As built

`python/perpcarry/ingestion/fetch_trades.py`, plus `binance_archive.py` for URL construction
(shared with the other M1 fetchers — the path shapes are not uniform, and `klines`' interval
segment is the trap). 22 tests: 21 offline against a 200-row real-archive fixture, 1 `network`.
CLI: `python -m perpcarry.ingestion.fetch_trades --symbol BTCUSDT --start … --end …`.

**The spec's predicted bug happened, exactly as predicted.** The aggressor-side mapping was wrong
on first write — but not by inverting the logic. The CSV is read with `dtype=str` to preserve
numeric precision, which makes `is_buyer_maker` the *strings* `"true"`/`"false"`, and
`bool("false")` is `True`. So `.astype(bool)` marked **every trade a sell**, uniformly and
silently. `test_real_fixture_has_both_sides` caught it on the first run. Parsing is now explicit
and rejects anything unrecognised.

This is the failure mode the spec called out — "no loud failure mode, so it gets a dedicated
test" — arriving through a mechanism the spec did not anticipate. The test earned its place; the
reasoning about *why* it was needed did not depend on guessing the mechanism right.

Two design choices worth noting:

- **`date` is derived per-trade from the timestamp**, not from the requested date, so monthly
  archives split into correct daily partitions and an out-of-day row cannot be misfiled.
- **`backfill` refuses to skip a missing month unless `allow_missing` is passed.** A 404 usually
  means the symbol was not yet listed (`0GUSDT` 404s in 2024-09), which is explainable — but
  explainable gaps must be acknowledged, not absorbed. Skipped months are returned for the caller
  to record in M1-T4's allowlist.

**Verified by mutation, 7/7 defects detected**, each by exactly one named test: side inverted,
date taken from the request, gaps never reported, gapped month stored anyway, schema drift
undetected, 404 silently skipped, checksum never fetched.

### What the pre-push review changed

Six findings, one of them serious.

**Cache poisoning of the real data root (serious).** `cached_fetch` writes into `data/.cache/`
under the archive's own filename, and tests were not isolated from it — so a test serving a
synthetic payload left `data/.cache/0GUSDT-trades-2026-08.zip` containing a 199-row punched
fixture. A later real backfill would have reused it: fabricated trades entering the corpus, named
and shaped like genuine archive data. Fixed structurally with an autouse `conftest.py` fixture
repointing `PERPCARRY_DATA_ROOT` per test, plus tests asserting the cache stays inside it.

**Continuity was not checked across month boundaries.** The acceptance criterion says "contiguous
within *and across* days"; per-month checks cannot see a wholly missing file between two intact
months. `backfill` now carries the last ID across iterations — and resets it after an allowed skip,
since a skipped month breaks the sequence legitimately.

Also fixed: duplicates were reported as "gaps" despite having a different cause (overlapping
re-fetch, not lost data) and now have their own check; `klines_volume` skipped checksum
verification that every other download performs; `total_quantity`'s docstring claimed to sum from
the CSV strings when it sums float64 reprs; a dead `skiprows=0`.

Two further gaps were then found by asking what the suite did *not* cover:

- **`backfill` could store nothing at all and all 47 tests passed.** Every test covered refusal
  behaviour; the module's actual purpose had no positive assertion.
- **A monthly archive whose rows spill into the next month silently loses them.** Those rows land
  in the next month's partition, and writing that month deletes them (`write_parquet` uses
  `delete_matching`) — demonstrated: two rows in, one row gone. Observed archives are clean, but
  the failure is invisible, so `backfill` now refuses rather than trusts.

**Then mutation testing found three of those fixes were themselves untested** — the boundary reset,
the duplicate check and the klines checksum all survived deletion. The skip test in particular
began with a 404, so the boundary state was never set and the reset it claimed to cover was never
exercised. All three now fail when their fix is removed.

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

**Q1 — RESOLVED.** The design doc's M1-T1 row now names the `trades` dataset explicitly and states
the reconciliation criterion in terms of `klines` volume. If `trades` proves impractically large
for the chosen range, the criterion must be relaxed to monotonicity and the design doc updated in
the same change — do not switch to `aggTrades` while leaving the criterion as written.

**Q2 — RESOLVED: 2024-08-01 through 2026-08-01, continuous.** This is M1-T3's 24-month book window
(2024-09-01 → 2026-08-01) plus one month of lead-in so ADV and the volume profile are defined on
the first book day rather than starting cold. Trades are cheap and continuous coverage helps on
days without book data, so there is no reason to sample.

Use **monthly** archives for the backfill and daily only for any tail — 24 monthly files per symbol
instead of ~730 daily ones.

**Q3 — RESOLVED.** OD-1 is settled on Binance USD-M. The archive is reachable and current; the
live API is geo-blocked but unused. See `external-dependencies-audit.md`.

**Q4 — RESOLVED (a note, not a decision).** `klines` lives under an **interval subdirectory**
(`daily/klines/{SYM}/1m/{SYM}-1m-{date}.zip`), unlike every other dataset. The reconciliation code
must not reuse the flat path builder.

**Q5 — RESOLVED: the volume reconciliation is exact, not approximate.** Measured across three
symbols including 1.9M fractional-quantity `ETHUSDT` trades: summed trade quantity equals summed 1m
`klines` volume with zero difference. Assert equality using `Decimal` summed from the raw strings.
Full measurements in `M1-T4-validate-data.md` Q1.
