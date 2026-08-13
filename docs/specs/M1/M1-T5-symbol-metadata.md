# M1-T5 — Symbol metadata derivation

**Milestone:** M1
**Status:** Draft
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

**Verified 2026-08-12** on `0GUSDT` 2026-08-01 (51,469 trades): recovers tick `0.01`, step `1`.

Use `decimal.Decimal`, not floats — computing a GCD over binary floats will produce nonsense.
Scale to integers by the maximum observed decimal exponent, then reduce.

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

**Q1 — how long a window?** Suggest one month of trades per symbol; cheap for the archive and long
enough that the stability check is meaningful.

**Q2 — is an overestimated tick actually harmful for the thin symbol (OD-3)?** It affects M2's book
granularity and M4's normalisation. Worth quantifying once the altcoin is chosen rather than
assuming it is negligible.
