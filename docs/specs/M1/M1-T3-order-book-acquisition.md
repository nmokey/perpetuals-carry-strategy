# M1-T3 — Order book historical data acquisition

**Milestone:** M1
**Status:** Draft — ready to implement. Unblocked 2026-08-12 by OD-2's resolution; licence read and
all open questions resolved the same day.
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

**Integrity.** The vendor publishes no `.CHECKSUM` files (verified: 404), so archive-style
verification is unavailable. Use successful gzip inflation as the signal — verified 2026-08-12
that a truncated `.gz` raises `EOFError: Compressed file ended before the end-of-stream marker was
reached`, so a partial download cannot pass silently. `download.fetch_checksum` already returns
`None` here rather than failing, so nothing needs changing in M0-T6.

## Licence — read 2026-08-12

The free samples are governed by the vendor's standard Terms of Service; there is no separate
sample licence. What it permits and forbids, for this project specifically:

**Permitted.** "Permitted Use" is defined as *internal business, research, educational or personal
use* (Clause 9.1). The project's core use — calibrating an impact model for a research writeup —
falls squarely inside it. No API key, no account, no fee.

**Forbidden, and this constrains the repo.** Clause 9.2(2) prohibits redistributing the Data,
"except for reselling or redistributing aggregated and calculated Derived Data" — where no raw Data
is exposed and it "cannot reasonably be reconstructed". OHLC/OHLCV at ≥10-minute resolution is the
worked example.

Practical rules, which are stricter than convention C9 and must be followed:

| Action | Allowed? |
|---|---|
| Download and analyse locally | Yes |
| Commit raw book rows as a test fixture | **No** — use synthetic fixtures or Binance-archive rows |
| Let book data reach a CI cache or build artifact | **No** |
| Publish fitted impact coefficients, capacity curves, slippage-vs-size plots | Yes — aggregated, calculated, non-reconstructible |
| Publish book snapshots, per-level depth, or anything permitting reconstruction | **No** |
| Use it in a product or service | **No** (Clause 9.2.1) — not in scope anyway |

**One residual ambiguity, flagged not resolved.** The terms explicitly bless redistributing derived
data in the coarse-candle form; they do not explicitly address publishing research findings. A
capacity curve exposes no raw data and cannot reconstruct a book, so it sits comfortably within the
*intent* of 9.2(2) — but "comfortably within the intent" is not "expressly permitted". Since M9's
output is public and resume-facing, the low-cost move is to email the vendor for written
confirmation before publishing, and to credit them regardless. Not a blocker for M1–M8.

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

**Q1 — RESOLVED: 24 months, 2024-09-01 through 2026-08-01 inclusive.** That is 24 book days per
symbol. Reasoning: it spans enough distinct market regimes for the impact model to be validated out
of sample on *different* months rather than a random split of one; it sits entirely inside the
funding history (which runs to contract inception, so M6 is unconstrained by this choice); and at
~449 MB/day it is ~10.8 GB compressed for BTC, which is large but tractable on a laptop. Start by
pulling **3 months** to exercise the pipeline end to end before committing to the full 24 — a
mistake found on 10.8 GB of downloads is expensive.

**Q2 — RESOLVED.** Terms read 2026-08-12; see the Licence section above. Research use is permitted;
raw data must never be committed, published, or reach CI. One residual ambiguity about publishing
derived findings is flagged there — worth a confirmation email before M9, not a blocker now.

**Q3 — RESOLVED: pull BTCUSDT plus two altcoin candidates now.** Unlike live recording nothing is
lost by waiting, so this is purely about avoiding a second bulk pull. Suggest `ETHUSDT` (liquid
control, second data point for the model) and one thin name — `0GUSDT` has verified trades, funding
and book coverage, and its tick/step are already derived. OD-3's final choice stays deferred to M8;
this only ensures the data exists when it is made.

**Q4 — RESOLVED: UTC-aligned, verified 2026-08-12** by downloading `0GUSDT` 2026-06-01 in full.
First row `2026-06-01T00:00:01.245Z`, last `2026-06-01T23:59:59.598Z` — the same UTC day boundary
the Binance archive uses, so book days and trade days align with no session offset. The file also
opens with a genuine `is_snapshot=true` block (~2,823 rows for this symbol) and timestamps are
microseconds, both as specced above.

**Finding (not an open question) — it improves Q1's arithmetic.** File size scales with liquidity far more sharply
than assumed: `0GUSDT` is **10 MB** for a full book day against BTCUSDT's 449 MB (`DOGEUSDT`:
123 MB). So the 24-month pull is ~10.8 GB for BTC but only ~240 MB for a thin altcoin. Pulling
several altcoin candidates is therefore nearly free, and the storage decision is really a decision
about BTC alone.
