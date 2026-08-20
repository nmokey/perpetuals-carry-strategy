# M1-T5 — Symbol metadata derivation

**Milestone:** M1
**Status:** **Complete 2026-08-20.** `derive_symbol_meta.py` + committed `symbol_meta.json`
(`0GUSDT`, `BTCUSDT`, `ETHUSDT`); 42 tests, 12/12 mutations caught. Every measurement in the table
below reproduced exactly on re-derivation. Resolves B-007.
**Depends on:** M1-T1
**Design doc:** Section 5 (M1), OD-1

## Goal

Recover per-symbol tick size and step size, and commit them as a reviewed lookup table. M2 needs
tick size to reason about price-level granularity, M4-T3 needs step size to normalise order sizes,
and M7-T2 needs both to produce sizes that could actually be submitted.

This task exists because the audit found the metadata has **no obtainable authoritative source**:
`exchangeInfo` is geo-blocked, the S3 archive carries no metadata tree, and the vendor's
instruments API is paid-only (`"available only for active pro and business subscriptions"`). The
design doc never listed this as a dependency, which is why it went unnoticed until M1 was specced.

## Approach

Infer from observed data. For a symbol, over a long window of `trades`:

- **tick size** = GCD of the distinct observed prices
- **step size** = GCD of the distinct observed quantities

**Verified 2026-08-12** across three disjoint days per symbol:

| Symbol | Window | Tick | Step | Distinct prices | Trades |
|---|---|---|---|---|---|
| `0GUSDT` | 2026-03-02 | `0.0001` | `1` | 321 | 202,668 |
| `0GUSDT` | 2026-07-15 | `0.0001` | `1` | 371 | 472,756 |
| `0GUSDT` | 2026-08-01 | `0.0001` | `1` | 81 | 51,469 |
| `ETHUSDT` | 2026-03-02 | `0.01` | `0.001` | 17,267 | 12,411,033 |
| `ETHUSDT` | 2026-07-15 | `0.01` | `0.001` | 8,344 | 5,212,944 |
| `ETHUSDT` | 2026-08-01 | `0.01` | `0.001` | 5,384 | 1,893,589 |

Stable across every window, including the thin 81-distinct-price day — more robust than feared.

Use `decimal.Decimal`, not floats: a GCD over binary floats produces nonsense. Scale to integers by
the **maximum** observed decimal exponent, then reduce.

> **That `max` is load-bearing.** The first probe used `min` and reported `0.0001` as `0.01` — a
> 100× error that looked entirely plausible. It produced a valid-looking number, not an exception,
> which is precisely why test 1 below pins the derivation against a known grid.

### The limitation, stated plainly

This recovers *observed* granularity, which equals the true tick only when enough distinct values
occur. For a liquid symbol over a full day it is safe; for a thin symbol over a short window it can
**overestimate** the tick (if no two trades ever landed one tick apart, the GCD is a multiple of
the truth). It can never underestimate.

Two consequences:
- Compute over the longest available window, not a single day.
- Stability across independent windows is the confidence check, and it is the acceptance criterion.

An overestimated tick would make the book look coarser than it is and would quietly bias impact
estimates. This is worth an explicit caveat in the M9 writeup for any thin symbol.

## Output

A committed, human-readable table — `python/perpcarry/ingestion/symbol_meta.json` or similar — with
one entry per symbol recording tick size, step size, the window used, the trade count, and the
derivation date. Committed rather than computed at runtime so it is reviewable in diffs and stable
across runs, and because a value that silently changes between runs would make backtests
irreproducible.

## Acceptance criteria

Proposed for the design doc Section 5 M1 table:

> Tick and step size recovered by GCD over a long trades window; recovered values stable across
> independent windows for the same symbol

| # | Test | Where |
|---|---|---|
| 1 | Synthetic trades on a known tick grid recover exactly that tick | `tests/ingestion/test_symbol_meta.py` |
| 2 | Two disjoint real windows for the same symbol agree | same, marked `network` |
| 3 | Decimal arithmetic throughout — a float-based implementation fails this test | same |
| 4 | A too-thin window is flagged as low-confidence rather than returning a confident wrong answer | same |
| 5 | The committed table round-trips and matches freshly derived values for a spot-checked symbol | same |

Test 4 is the one that keeps this honest: the failure mode is a plausible wrong number, not an
error, so the code must be able to say "not enough data" (convention C12).

## Out of scope

- Contract multiplier and minimum notional. Not derivable this way, and not needed until M7-T2 —
  revisit there. Note this means the sizing logic may hit a second metadata gap later.
- Historical changes to tick size. Venues do re-tick symbols; this task assumes a single current
  value per symbol. If a symbol was re-ticked inside the study window, the GCD silently returns the
  finer of the two. Flag if the stability check (test 2) disagrees across time.

## Open questions

**Q1 — RESOLVED: three sampled days spanning ≥3 months, not a contiguous month.** The measurements
above show the estimate is already stable on a single thin day, so a full month buys little; what
buys confidence is *disjoint* windows, which also detects a mid-window re-tick. Concretely: sample
the first, middle and last month of the study window, one day each, and require all three to agree.
Cheaper than a contiguous month and a strictly better check.

**Q2 — RESOLVED: overestimation is a real risk but the stability check catches it.** All three
`0GUSDT` windows agree despite one having only 81 distinct prices. The demonstrated failure mode
was not thin data but a **bug in the exponent handling**, which is now pinned by test 1. If the
three windows ever disagree, the correct response is to widen the window rather than pick the
finest — a disagreement may equally mean the venue re-ticked the symbol (see Out of scope).
