# M1-T4 — Data validation / QA pass

**Milestone:** M1
**Status:** **Complete 2026-08-20.** `validate_data.py` + committed
`data_quality_allowlist.toml`; 43 tests, 26/26 mutations caught. Validated against a real
assembled corpus (0GUSDT, June 2026): 354 checks, zero failures. Two spec assumptions turned
out wrong — `trade_id` contiguity (D-015) and the allowlist format (D-016).
**Depends on:** M1-T1, M1-T2, M1-T3, M1-T5
**Design doc:** Section 3, Section 4.1, Section 5 (M1)

## Goal

Produce `validate_data.py`: a standalone pass over the assembled dataset that answers "is this data
fit to build research on?" and fails loudly when it is not. Every downstream milestone consumes
this output, and data defects are the class of bug that produces plausible-looking wrong numbers
rather than a crash — the worst kind for this project.

The distinction from the per-fetcher tests in M1-T1/T2: those validate *a download*. This validates
*the corpus* — coverage, cross-dataset consistency, and things only visible in aggregate.

## Checks

Grouped by what they protect against.

### Integrity

| Check | Rationale |
|---|---|
| Archive `.CHECKSUM` verified for every downloaded file | A truncated download otherwise looks like a quiet trading day |
| Parquet reads back with the exact Section 3 schema and dtypes | Catches upstream schema drift |

### Completeness

| Check | Rationale |
|---|---|
| No missing dates in the requested range, per dataset per symbol | A missing day silently shortens the backtest |
| Funding: settlement count matches `24 / funding_interval_hours × days` | The M1-T2 criterion, applied corpus-wide |
| Trades: `trade_id` contiguous within each day, and continuous *across* day boundaries | Per-day checks miss a whole missing day between two intact ones |

### Consistency

| Check | Rationale |
|---|---|
| No duplicate `(symbol, trade_id)` | Re-fetch bugs and overlapping monthly/daily pulls |
| `timestamp` non-decreasing within each partition | Section 5's "non-monotonic sequences" criterion |
| Daily traded volume reconciles against `klines` **exactly** | Independent cross-source check — see Q1; this is an equality, not a tolerance |
| Every funding settlement falls inside the trades coverage window | Detects legs assembled over mismatched ranges |
| **All datasets come from the same venue** | Guards the failure mode M1-T3 identifies as fatal to the result |

### Plausibility

| Check | Rationale |
|---|---|
| Prices and quantities finite and positive | |
| Funding rates within the symbol's cap | |
| No zero-trade days for a liquid symbol | A structurally empty day means a fetch bug, not a quiet market |

### Order book (unblocked by OD-2's resolution)

| Check | Rationale |
|---|---|
| Each book day opens with an `is_snapshot` block | Without it the day cannot be replayed from a known state |
| `amount = 0` rows are present | Their absence means an upstream clean step silently dropped level removals |
| Book days are first-of-month only, and each has a matching `book_snapshot_25` | The free tier's shape; a missing reference file makes M2-T2 unverifiable |
| Book coverage dates fall inside the trades/funding coverage window | Prevents calibrating impact on a period the backtest never sees |

**Sequence continuity is not checkable.** This feed carries no `update_id` (§3.2), so dropped
updates cannot be detected by sequence gap. Replay-vs-snapshot agreement (M2-T2) is the substitute,
and it is weaker — the validator should not imply otherwise.

## Output

A machine-readable report — Parquet or JSON, one row per (dataset, symbol, date, check) with
pass/fail and a detail field — plus a human-readable summary. Two reasons for the structured form:
the M9 writeup should be able to state data coverage and known gaps factually rather than from
memory, and gaps found here need to be *tracked*, not just printed once.

Exit code is non-zero on any failure so the script is usable as a gate.

## Acceptance criteria

Copied verbatim from the design doc Section 5 table:

> Zero unexplained gaps, duplicate timestamps, or non-monotonic sequences on final dataset

Expanded into checkable tests:

| # | Test | Where |
|---|---|---|
| 1 | Each check fires on a fixture deliberately corrupted in exactly that way, and only that check fires | `tests/ingestion/test_validate_data.py` |
| 2 | A clean fixture passes every check with a zero exit code | same |
| 3 | The report round-trips and names the offending `(dataset, symbol, date)` for each failure | same |
| 4 | Cross-day `trade_id` continuity catches a wholly missing day between two intact days | same |
| 5 | A mixed-venue corpus is rejected | same |

**Test 1 is the point of this task** (convention C12). A validator that cannot be shown to fail on
known-bad input provides false confidence, which is worse than no validator — it converts "we
didn't check" into "we checked and it was fine".

Note the word **"unexplained"** in the criterion: some gaps are real and legitimate (venue
downtime, symbol listing date). The report needs an explicit allowlist mechanism — a gap
acknowledged with a documented reason passes; a gap nobody has looked at fails. Without this the
criterion is either unachievable or gets satisfied by weakening the checks.

## Out of scope

- Fixing bad data. This task reports; the fetchers fix.
- Book-data validation — M1-T3.
- Statistical properties (stationarity, ACF) — that is M6-T1's exploratory analysis, not QA.

## Open questions

**Q1 — RESOLVED: require exact equality.** Measured 2026-08-12 on 2026-08-01 data — summed trade
quantity equals summed 1m `klines` volume with **zero** difference:

| Symbol | Trades | Σ trade qty | Σ klines volume | Rel. diff |
|---|---|---|---|---|
| `0GUSDT` | 51,469 | 24270655.0 | 24270655 | 0 |
| `DOGEUSDT` | 542,309 | 3249377469.0 | 3249377469 | 0 |
| `ETHUSDT` | 1,893,589 | 1873612.610 | 1873612.610 | 0 |

`ETHUSDT` was included deliberately: fractional quantities (step `0.001`) across 1.9M trades, where
float summation error was the plausible worry. Both float64 and exact `Decimal` summation agree.

Sum with `Decimal` from the raw strings anyway — float64 happening to agree at this scale is not a
guarantee at another, and an exact check that occasionally needs a documented exception is more
useful than a tolerance wide enough to hide a genuinely missing chunk of a day. If a symbol ever
fails, that is a finding to investigate, not a threshold to widen.

**Q2 — RESOLVED: `data_quality_allowlist.yaml`, committed at the repo root of the ingestion
package.** One entry per acknowledged gap: dataset, symbol, date range, reason, and the date it was
acknowledged. Reviewable in diffs, and it doubles as the source for the M9 writeup's data-caveats
section — which is the real reason it must be a file rather than a runtime flag.

**Q3 — RESOLVED: nightly, against committed fixtures.** The real corpus cannot go in CI (size, and
the vendor licence forbids redistributing raw book data — see M1-T3). Fixtures must therefore be
either synthetic or drawn from the Binance archive only, **never** vendor book rows. This keeps the
checks themselves from rotting without putting data in the repo (C10, C9).
