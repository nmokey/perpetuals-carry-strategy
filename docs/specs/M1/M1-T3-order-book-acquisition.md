# M1-T3 — Order book historical data acquisition

**Milestone:** M1
**Status:** Draft — **unblocked 2026-08-12** by OD-2's resolution (was Blocked)
**Depends on:** M0-T4, M0-T6, OD-1 (resolved: Binance USD-M), OD-2 (resolved: vendor free tier)
**Design doc:** Section 3.2, Section 4.1, OD-2, Risk R1

## Goal

Produce `fetch_book.py`, downloading L2 order book data sufficient to reconstruct book state at
arbitrary timestamps within each downloaded day. This is what makes the project's central claim
possible — that execution costs are *calibrated* from real book data rather than assumed — so the
fidelity obtained here bounds what the writeup may honestly assert.

## Source

Tardis.dev free tier, `binance-futures`, no API key required:

```
https://datasets.tardis.dev/v1/binance-futures/{type}/{YYYY}/{MM}/{DD}/{SYMBOL}.csv.gz
```

| Type | Use |
|---|---|
| `incremental_book_L2` | The primary dataset — snapshot + diffs |
| `book_snapshot_25` | Independent reference for validating replay (M2-T2) |

**Coverage, verified 2026-08-12 by probe:** the **first day of every month** returns HTTP 200;
every other day returns 401. Confirmed back to 2020-01-01, for altcoins (`DOGEUSDT`) and for other
venues. Do not write a date loop that assumes contiguous days — it will 401 on the 2nd.

Schema: `exchange, symbol, timestamp, local_timestamp, is_snapshot, side, price, amount`, with
`amount = 0` meaning the level was removed. `timestamp` is **microseconds**, not milliseconds —
normalise on ingest to match every other dataset in §3.

Size: ~449 MB compressed per BTCUSDT day (measured). Stream; never load whole.

## Why sparse coverage is acceptable

One day per month is not continuous, and that is fine given the architecture — but the reasoning
must be stated in the writeup rather than assumed:

M5 calibrates an impact *model* from book data. M7's backtest consumes the fitted model and never
touches the raw book. So what is required is enough book days to fit the model and validate it out
of sample, not book data at every backtest decision point. Twelve days a year over several years
gives both cross-sectional variation (order size) and temporal variation (across regimes).

What is genuinely lost: the impact model cannot be conditioned on same-day book state during the
backtest, so it is applied as a static (or slowly time-varying) function. That is a real
limitation and belongs in the M9 caveats.

## Deviations from the design doc's original assumptions

**No `update_id`.** §3.2 originally specified a sequence number for dropped-diff detection. This
feed has none. Continuity is instead established by each file opening with an `is_snapshot` block,
and by validating replayed state against `book_snapshot_25`. This is weaker than sequence checking
and the design doc now says so.

**`local_timestamp` is new and worth keeping.** The gap between it and `timestamp` is the vendor's
observed capture latency — useful for judging whether the data supports latency-sensitive claims
(it does not, particularly).

## Output

`data/book/symbol={SYMBOL}/date={YYYY-MM-DD}/*.parquet`, plus the reference snapshots under
`data/book_snapshot/...`. Given the size, converting CSV → Parquet on ingest and deleting the
source archive is worth doing; the download cache (M0-T6) keeps re-fetching cheap during
development.

## Acceptance criteria

From the design doc Section 5 table, as revised:

> Book state reconstructable at any timestamp within a downloaded day; replayed top-25 levels
> match the same day's `book_snapshot_25`

| # | Test | Where |
|---|---|---|
| 1 | Downloaded day parses to the §3.2 schema with µs→ms normalisation applied | `tests/ingestion/test_fetch_book.py` |
| 2 | The file opens with an `is_snapshot` block; a file that does not is rejected | same |
| 3 | `amount = 0` rows are preserved as removals, not silently dropped as zero-quantity noise | same |
| 4 | A non-first-of-month date fails with a clear message naming the free-tier limitation, not a bare 401 | same |
| 5 | Ingest is streaming — memory stays bounded on a large fixture | same |
| 6 | Both `incremental_book_L2` and `book_snapshot_25` are fetched for each requested day | same |

Test 3 guards a plausible mistake: filtering `quantity > 0` while cleaning would turn every level
deletion into a silently persistent phantom level, and the book would drift without ever erroring.

Full replay correctness is M2-T2's criterion, not this task's — here we only ensure the inputs it
needs are present and well-formed.

## Out of scope

- Book reconstruction itself — M2.
- Any live capture. The venue's WebSocket is geo-blocked and unused (§4.1).

## Open questions

**Q1 — how many months?** Recommend 12–24, chosen to overlap the funding history used by M6. At
~449 MB/day compressed that is ~5.4–10.8 GB. Needs a decision before the first bulk pull.

**Q2 — vendor licensing.** The free tier's terms have **not** been read. Must be done before
relying on the data. It must never be committed or reach CI caches (C9).

**Q3 — which symbols?** BTC is settled. OD-3 defers the altcoin to M8, but book days are tied to
calendar dates, so pulling a couple of plausible candidates now costs only disk and avoids
re-pulling later. Unlike live recording, nothing is lost by waiting — the archive is historical —
so this is a convenience question, not a deadline.
