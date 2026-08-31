# M4-T3 — Order size normalization

**Milestone:** M4
**Status:** Draft
**Depends on:** M4-T2; M1-T1/M1-T2 (archive URL construction, complete — `klines_daily_url` already
exists and is reused here rather than restated)
**Design doc:** Section 4.3, Section 5 (M4), Section 3.1

## Goal

Express an order size in units that mean the same thing across symbols and dates: a fraction of
average daily volume, and a fraction of visible top-N book depth. "Buy 50,000 0G" is not comparable
to "buy 50,000 BTC"; "buy 1% of ADV" is. M8's cross-symbol comparison is impossible without this,
and M5's calibration is far less useful — a fit in raw units describes one symbol in one liquidity
regime.

## Acceptance criteria

Copied verbatim from the design doc Section 5 table:

> Unit tested against known ADV figures for test symbol/date

**"Known figures" did not exist when this was written, and getting them is most of the task.** The
venue API is geo-blocked (B-004), so the only ADV available was one computed from our own trades
corpus — and testing that against itself is the trap M3-T3's "checkpoint" fell into and M1-T4's
validator fell into before it: two copies of one assumption agreeing by construction.

**Resolved by an independent source that is actually reachable.** `data.binance.vision` publishes
daily **klines**, whose `volume` and `quote_volume` columns are the venue's own aggregation of the
same trades, computed by someone else. `binance_archive.klines_daily_url` already exists from M1-T1.
So ADV derived from our `trades` corpus gets checked against Binance's published bar volume for the
same symbol-day — a genuine cross-check, not a restatement. Agreement is a real signal: it would
fail if our trades ingest silently dropped rows, which no count-based check in this project would
otherwise catch.

Expanded into checkable tests:

| # | Test | Where |
|---|---|---|
| 1 | `fetch_klines` builds the right URL and parses the archive's column order, asserted against the documented schema rather than a restated copy | `tests/ingestion/test_fetch_klines.py` |
| 2 | ADV over a synthetic trades fixture equals the hand-computed mean of daily volumes | `tests/models/test_order_size.py` |
| 3 | ADV excludes partial days at the window edges, or includes them deliberately — whichever, asserted, so the denominator is never silently wrong by a day | same |
| 4 | **Cross-check:** daily volume summed from the `trades` corpus matches the klines `volume` for the same symbol-day within a stated tolerance | same, `@pytest.mark.network` |
| 5 | Depth normalization: size as a fraction of summed top-N quantity on the side the order would consume — a buy against the ask side | same |
| 6 | Depth at N > available levels reports the true level count alongside, so a thin book is visible rather than inflating the fraction's denominator | same |
| 7 | Round-trip: converting a size to %ADV and back returns the original size | same |
| 8 | A zero or missing ADV raises rather than producing an infinite or NaN fraction | same |
| 9 | Sizes round to `step_size` from the committed `symbol_meta.json`, read via `derive_symbol_meta.load_table()` — never a literal | same |

Test 4 is the criterion. Tests 2 and 3 exist so that when it fails, the failure has a name.

## Design

**Two normalizations, because they answer different questions.** %ADV is the standard axis in the
impact literature and the one M8 compares across symbols. %depth is the one that predicts *this
order's* cost, because it is the liquidity actually present at that instant — and the two diverge
exactly where it matters, on a thin book during a volume spike. M5 fits against both and reports
which explains more; that comparison is itself a finding worth having.

**ADV is computed, klines are the check — not the source.** The corpus's `trades` is what M5 and M7
consume, so the ADV that feeds calibration must come from the same rows, or the study is calibrated
against one dataset and executed against another. Klines validate that computation; they do not
replace it. (Same reasoning as D-018's harness: validate the thing you actually use.)

**Where it lives.** Python, in `python/perpcarry/models/order_size.py`, and this is a deviation from
the milestone's "(C++)" heading worth stating: normalization is arithmetic over corpus aggregates,
needs symbol identity and committed metadata, and has no place in `perpcarry_core`, which
deliberately has no data dependencies (M4-T1 Q2 turned down the same thing for the same reason). The
depth half reads levels through the M3-T1 bindings.

`fetch_klines.py` joins `python/perpcarry/ingestion/`, minimal by intent: one dataset, daily
granularity, reusing `download.py`'s streamed fetch, checksum and cache exactly as the other three
fetchers do. It exists to be a cross-check, not to become a fourth first-class dataset.

## Data

- **In:** `data/trades/symbol=.../date=...` (existing), `data/klines/symbol=.../date=...` (new, same
  partitioned Parquet layout via `storage.write_parquet`), and book levels through the bindings.
- **Out:** functions, not files. The calibration dataset that uses them is M5-T1.
- `symbol_meta.json` supplies `step_size`; it is committed data, never recomputed at runtime.

## Invariants this task must not break

**No look-ahead.** ADV must be computed from a window *ending at or before* the instant it
normalizes. An ADV over the full sample used to size an order at day 3 is leakage of exactly the
kind ranked first among things that invalidate this work — and it is the natural way to write it,
which is why it needs a test rather than a comment. M5-T1's sweep is where it would bite.

**Determinism.** Same corpus, same window, same number.

**Honest limitations.** Depth normalization sees only the visible book, and only the top N of it —
and below level 25 that book is itself unvalidated (D-019). %depth on a large N inherits that.

## Out of scope

- Fitting anything to these normalized sizes — **M5**.
- Choosing which sizes to sweep — **M5-T1**.
- ADV-based *position sizing* — **M7-T2** (OD-10), a strategy decision, not a unit conversion.
- Turnover, order-book imbalance, or any other liquidity measure. Two axes are enough to compare;
  a third with no consumer is speculative.

## Open questions

**Q1 — what window for ADV: 30 days, or the trailing month?**
Recommendation: a caller-supplied trailing window defaulting to 30 days, computed strictly from days
before the instant being normalized. The number matters less than that it is explicit and rolling;
a fixed calendar month would make an order's %ADV jump discontinuously at month boundaries.

**Q2 — what tolerance for the klines cross-check (test 4)?**
Recommendation: decide it from a first measurement rather than picking one now, and record the
observed difference. The two aggregations may differ for documented reasons (bar boundary handling,
inclusion of block trades), and a tolerance chosen before seeing the discrepancy is a tolerance
chosen to pass. If they agree exactly, assert exactly — the M2-T2 experience is that the strict
criterion is often available and always better.

**Q3 — should `klines` become a validated corpus dataset with a `validate_data` check?**
Recommendation: not yet. It is a cross-check input, not a study input, and adding it to the
corpus-health gate would make a missing optional dataset fail the whole corpus. Revisit if M8 ends
up using bar data for anything.
