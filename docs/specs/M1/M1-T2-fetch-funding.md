# M1-T2 — Historical funding rate downloader

**Milestone:** M1
**Status:** Ready to implement — all open questions resolved 2026-08-12. One non-blocking data question remains (see Open questions).
**Depends on:** M0-T4 (complete), M0-T6 (HTTP client — blocks this task).
OD-1 **resolved**: Binance USD-M futures.
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

**Both deviations are now resolved in the design doc; §3.3 has been amended to match reality.**

**`mark_price` is dropped.** The archive does not carry it, and it is unused before M7-T4 — which
should source settlement price from `markPriceKlines` at that point rather than carrying a
mostly-unused column through the whole pipeline. Do not emit the column as null.

**`funding_interval_hours` is carried through.** It is per-symbol and not a constant 8 (OD-3's
altcoin may differ), and the strategy cannot annualise without it. Nothing anywhere may hard-code
8h or `× 3` per day.

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
| 5 | Output matches §3.3 exactly: `funding_interval_hours` present, `mark_price` absent — not null | same |
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

**Q1 — RESOLVED: drop `mark_price`.** §3.3 amended accordingly on 2026-08-12.

**Q2 — RESOLVED: fetch the full available history per symbol, back to contract inception.** At
~90–180 rows/month it is negligible in size, and M6's AR(1) fit benefits from every observation.
The backtest window remains the shorter book-constrained one (M1-T3: 2024-09 → 2026-08).

This asymmetry needs stating in the writeup rather than quietly exploited: the funding *model* can
be estimated on years of data while the *execution cost* model rests on a sparse sample of book
days. Those are different evidential bases for the two halves of the edge calculation, and a
reader is entitled to know which half is thinner.

**Q3 — RESOLVED, and the answer is no. Measured 2026-08-12 (June 2026):**

| Symbol | Interval | Settlements | Funding rate range |
|---|---|---|---|
| `BTCUSDT` | 8h | 90 | −0.67 bp … +1.00 bp |
| `ETHUSDT` | 8h | 90 | −1.02 bp … +1.00 bp |
| `DOGEUSDT` | 8h | 90 | −0.81 bp … +1.00 bp |
| `0GUSDT` | **4h** | 180 | −23.9 bp … +0.50 bp |
| `1000BONKUSDT` | **4h** | 179 | −2.10 bp … +0.50 bp |

The thin symbols settle **every 4 hours, not 8** — so the altcoin leg, which is the entire point of
M8-T2, is exactly where a hard-coded 8h or `× 3`/day would break. Always read
`funding_interval_hours`. This also refines OD-1's "8h for most symbols": true for majors,
false for the class of symbol this project deliberately studies.

Note the rate ranges too: `0GUSDT` reaches −23.9 bp per 4h settlement against BTC's −0.67 bp per
8h. Six settlements a day at that magnitude is a far larger gross carry — and precisely why the
execution-cost question matters more for thin symbols than liquid ones.

**Q4 — RESOLVED: end the window at the last complete month.** The archive is monthly-only, so the
current month is absent or partial until it closes. Acceptance test 7 covers refusing to write a
partial month silently.

**Open, non-blocking — `1000BONKUSDT` is missing a settlement.** June 2026 has 179 where 180
are expected — an 8h gap after 2026-06-24 00:00 UTC where 4h is expected. This is a genuine
upstream data gap, discovered while checking Q3, and it is the first concrete case for M1-T4's
allowlist: either it gets explained (a venue interval change mid-month?) or it stays flagged.
Useful as a real fixture for the completeness test rather than a synthesised one.
