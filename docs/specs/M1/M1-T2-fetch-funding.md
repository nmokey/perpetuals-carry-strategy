# M1-T2 — Historical funding rate downloader

**Milestone:** M1
**Status:** Draft
**Depends on:** M0-T4 (complete). OD-1 (venue) OPEN, default Binance Futures assumed.
**Design doc:** Section 3.3, Section 4.1, Section 5 (M1)

## Goal

Produce `fetch_funding.py`, which downloads realised funding rate history for a symbol and writes
it as Parquet conforming to design doc Section 3.3. This series is the entire input to the M6
Bayesian persistence model and one of the two terms in the strategy's edge calculation — if it is
wrong, every downstream result is wrong in a way no later test would catch.

## Data source

`https://data.binance.vision/data/futures/um/monthly/fundingRate/{SYMBOL}/{SYMBOL}-fundingRate-{YYYY-MM}.zip`

**Verified 2026-08-12** by direct download of `BTCUSDT-fundingRate-2026-06.zip`: 90 rows for a
30-day month, i.e. 3 settlements/day at 8h.

Note the constraints this source imposes:

- **Monthly granularity only.** There is no `daily/fundingRate/` path. The current month is
  therefore unavailable or partial until it closes — relevant if the backtest window runs to the
  present.
- **The REST endpoint is not an option.** `/fapi/v1/fundingRate` is geo-blocked from the US
  (verified: `"Service unavailable from a restricted location"`). The archive is S3-backed and
  unaffected. See B-004.

Actual CSV schema — **not** what design doc Section 3.3 specifies:

```
calc_time,funding_interval_hours,last_funding_rate
1780272000001,8,0.00005703
```

## Schema mapping and two real deviations

| Section 3.3 field | Source | Status |
|---|---|---|
| `symbol` | *(from path)* | Not a column; injected |
| `funding_time` | `calc_time` | Rename |
| `funding_rate` | `last_funding_rate` | Rename |
| `mark_price` | — | **Absent from this dataset** |

**Deviation 1 — `mark_price` is not available.** Section 3.3 specifies "Mark price at funding
settlement", which the funding archive does not carry. Two options, and this needs a decision
(Q1): join `markPriceKlines` at the settlement timestamp, or drop the column and have M7-T4
source the settlement price where it is actually needed. Do not silently emit the column as null.

**Deviation 2 — `funding_interval_hours` is a column, and it is per-symbol.** Section 3.3 does not
model it, but the strategy cannot annualise a funding rate without it, and it is not a constant
across symbols (OD-3's altcoin may not be 8h). Carry it through; it is more useful than
`mark_price`.

## Timestamp irregularity, verified

Settlement timestamps are *not* exactly regular. In the June 2026 sample, `calc_time` values end
in both `...0000` and `...0001`, so consecutive gaps measure 28,800,000 ms and 28,799,999 ms.
Naive integer-hour differencing reports a spurious "7 hour" gap.

Any calendar-completeness check must therefore compare against expected settlement times with a
tolerance of a few seconds, not assert exact equality. This is the one place M1-T2 is likely to
produce a false alarm.

## Output

`data/funding/symbol={SYMBOL}/date={YYYY-MM-DD}/*.parquet`. Partitioning by date is consistent
with the other datasets and cheap here (3 rows/day), though the volume would not require it.

## Acceptance criteria

Copied verbatim from the design doc Section 5 table:

> One row per funding interval per symbol; matches venue's published funding calendar

Expanded into checkable tests:

| # | Test | Where |
|---|---|---|
| 1 | Settlement count for a full month equals `24 / funding_interval_hours × days`, exactly | `tests/ingestion/test_fetch_funding.py` |
| 2 | Consecutive settlements are `funding_interval_hours` apart within a ±5s tolerance; the `...0001` jitter does **not** trigger a failure | same |
| 3 | A deliberately removed settlement is detected and reported with its expected timestamp | same |
| 4 | Rates are plausible: finite, and within the venue's funding rate cap for the symbol | same |
| 5 | Output matches the agreed schema exactly, including the Q1 resolution for `mark_price` | same |
| 6 | Re-fetching a month is idempotent | same |
| 7 | A partial current month is either refused or clearly flagged, never silently written as complete | same |

Test 2 is the one that would have been written wrong without checking the data first.

## Invariants this task must not break

**No look-ahead.** Funding settles *at* `funding_time` for the interval that just ended. A strategy
decision made at time *t* may use settlements with `funding_time <= t` and no others. The
off-by-one here — treating a settlement as known one interval early — is a textbook look-ahead leak
and would inflate every downstream result. M6-T3 and M7-T3 test this properly; this task's
contribution is to store the timestamp unambiguously and document its meaning in the module
docstring.

## Out of scope

- Predicted/current funding rate — this is realised history only.
- Premium index and mark price series — separate datasets, pull them if Q1 resolves that way.
- The funding *model* — M6.

## Open questions

**Q1 — `mark_price`: join or drop?** Recommend **drop** for M1: it is unused until M7-T4, joining
`markPriceKlines` adds a dataset and a timestamp-alignment problem now, and Section 3.3 can be
amended to reflect what the venue actually publishes. Needs confirmation, and the design doc
updated either way.

**Q2 — how far back?** Funding history extends to contract inception, which is far longer than the
usable book window (M1-T3). Suggest fetching generously — the data is ~90 rows/month — so the M6
model can be fit on a long series even if the backtest window is short. That asymmetry should be
stated explicitly in the writeup rather than quietly exploited.

**Q3 — does the altcoin (OD-3) share the 8h interval?** Unknown until the symbol is chosen. The
`funding_interval_hours` column makes this self-describing, but any hard-coded `× 3` per day
elsewhere in the codebase would silently break. Nothing should assume 8h.
