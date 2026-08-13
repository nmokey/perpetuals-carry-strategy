# M1-T4 — Data validation / QA pass

**Milestone:** M1
**Status:** Draft (book-data checks blocked behind M1-T3 / OD-2)
**Depends on:** M1-T1, M1-T2, M1-T3
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
| Daily traded volume reconciles against `klines` within tolerance | Independent cross-source check |
| Every funding settlement falls inside the trades coverage window | Detects legs assembled over mismatched ranges |
| **All datasets come from the same venue** | Guards the failure mode M1-T3 identifies as fatal to the result |

### Plausibility

| Check | Rationale |
|---|---|
| Prices and quantities finite and positive | |
| Funding rates within the symbol's cap | |
| No zero-trade days for a liquid symbol | A structurally empty day means a fetch bug, not a quiet market |

Book-data checks (sequence continuity, recorder downtime, snapshot agreement) are specified in
M1-T3 and are blocked with it.

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

**Q1 — what tolerance for the volume reconciliation?** `klines` volume and summed trade quantity
may differ slightly at day boundaries. A number needs choosing and justifying; "within 0.1%" is a
guess until measured on real data.

**Q2 — where does the allowlist live?** Suggest a committed YAML/JSON of acknowledged gaps with
dates and reasons, so it is reviewable in diffs. It is effectively a record of known data
limitations and should feed the M9 writeup's caveats section directly.

**Q3 — does this run in CI?** It needs real data, so not in the per-PR tier. Options: nightly
against a small committed fixture corpus, or purely on-demand. Recommend nightly on fixtures — it
keeps the checks themselves from rotting even though the real corpus is not in CI (C10).
