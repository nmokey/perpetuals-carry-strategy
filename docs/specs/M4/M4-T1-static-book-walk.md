# M4-T1 — Static book-walk simulator

**Milestone:** M4
**Status:** Draft
**Depends on:** M2-T2 (complete 2026-08-29). No open design decision gates this task; OD-5 is
resolved (**L2, D-017**) and constrains it hard — see below.
**Design doc:** Section 4.3, Section 5 (M4)

## Goal

`simulate_market_order(book, side, quantity)` — walk the reconstructed book and return what the
order actually filled at. This is the function that makes the project's central claim either true
or decorative: every downstream number, up to and including the capacity answer, is this walk
repeated across sizes and times. A subtly wrong walk produces a plausible slippage figure that
nothing downstream can detect, exactly as a subtly wrong book would.

## Acceptance criteria

Copied verbatim from the design doc Section 5 table:

> Unit tests against hand-computed book-walk examples

**That criterion is necessary and nowhere near sufficient**, and the spec says so rather than
meeting it and stopping. Hand-computed examples check the arithmetic on books someone chose. What
they cannot check is the behaviour on the book shapes a real day actually produces — crossed books,
sides thinner than the order, and walks past the depth any reference validates. Those are the tests
below that matter.

Expanded into checkable tests:

| # | Test | Where |
|---|---|---|
| 1 | Hand-computed walk: an order consuming exactly two whole levels returns the arithmetic mean weighted by size, to the last bit | `cpp/tests/test_impact_simulator.cpp` |
| 2 | Partial consumption of a level: an order smaller than the best level fills entirely at that price, and `levels_consumed == 1` | same |
| 3 | An order landing exactly on a level boundary consumes that level and no more — the classic off-by-one | same |
| 4 | A **buy** consumes the ask side and a **sell** consumes the bid side, asserted by price, not by inspection of a side field | same |
| 5 | Depth exhaustion: an order larger than the whole side fills partially, reports `filled_quantity < requested_quantity` and `exhausted_book`, and **never** invents liquidity at the last price | same |
| 6 | An empty side fills nothing, reports exhaustion, and returns no average price rather than a zero | same |
| 7 | A crossed book is reported through `crossed_at_entry`, not silently walked or silently refused | same |
| 8 | `levels_consumed` and `beyond_validated_depth` are reported, and the latter is true exactly when the walk passed level 25 | same |
| 9 | Slippage is reported against both mid and far touch, and the two differ by the half-spread on a one-level fill | same |
| 10 | Monotonicity on a fixed book: average price is non-improving in size for a buy, non-improving in size for a sell | same |
| 11 | Zero, negative, and non-finite quantities are rejected — not silently treated as a no-op fill | same |
| 12 | Determinism: the same book and order give a bit-identical result, and the walk does not mutate the book | same |

Test 10 is a property rather than an example, and it is the one that would catch a sign error that
every hand-computed case happened to agree with.

## What OD-5 already decided, and this task must not quietly undo

**Marketable orders only.** The only reachable book is price-level aggregated (D-017), so queue
position is unknowable. This simulator models an order that crosses the spread and pays it. It
cannot model a resting limit order's fill probability, and no amount of care here recovers that —
it is a property of the data, not of the code. Anything in M7 that wants passive execution is out
of reach and belongs in the M9 caveats alongside the other stated approximations.

## The depth problem, which is this task's real risk

**The book is validated 25 levels deep and this function walks deeper.** Demonstrated 2026-08-29
(D-019): deleting one real update well below the top of a ~1000-level book left the replay wrong
and the M2-T2 harness still passing, because no `book_snapshot_25` image describes that depth. By
level count the reference constrains ~2.5% of the book. There is no deeper reference on the free
tier, so the depth cannot be validated — only *reported*.

So every fill carries `levels_consumed` and `beyond_validated_depth`. A large order's cost is then
still a number, but it is a number that says how much of itself rests on unvalidated state, and
M5's calibration and M9's capacity curve can split on it. Burying this would be the "unstated
approximations" failure the north star ranks fourth among things that invalidate the work; hiding it
behind an average price would make it invisible, because an average price from a deep walk looks
exactly like one from a shallow walk.

**Do not "solve" it with a depth cap.** Truncating the walk at level 25 would make large orders look
*cheaper* than they are — the opposite of conservative — and would silently bound the capacity
answer by an artifact of the reference data rather than by the market.

## Crossed books are common, not an edge case

Measured on `0GUSDT` 2026-06-01: **82,356 of 1,299,113 updates (6.3%) leave the book crossed**, and
`OrderBook` reports crossing rather than repairing it (M2-T1), deliberately. A simulator that
samples times at random will therefore land on a crossed book often enough that whatever it does
there shows up in the calibration dataset.

Walking a crossed book is not meaningless — the levels are real — but the *mid* is, and slippage
against a mid that sits outside the spread is not a quantity anyone should regress on. So: walk it,
return the fill, set `crossed_at_entry`, and let M5 decide whether to exclude those samples. The
decision is recorded in the output rather than made silently here.

## Design

```cpp
// Deliberately NOT perpcarry::Side. `Side::Bid` names a side of the book; `OrderSide::Buy` names
// what an order does, and a buy consumes the *ask* side. Reusing one enum for both is how a sign
// error gets written that reads correctly (test 4).
enum class OrderSide : std::uint8_t { Buy, Sell };

struct Fill {
  double requested_quantity = 0.0;
  double filled_quantity = 0.0;      // < requested when the side ran out
  double notional = 0.0;             // sum(price * quantity) over consumed levels
  double average_price = 0.0;        // notional / filled_quantity; 0 only when nothing filled
  double worst_price = 0.0;          // the last level touched -- the tail of the cost
  double mid_at_entry = 0.0;
  double touch_at_entry = 0.0;       // best ask for a buy, best bid for a sell
  double slippage_vs_mid_bps = 0.0;
  double slippage_vs_touch_bps = 0.0;
  std::size_t levels_consumed = 0;
  bool exhausted_book = false;        // requested more than the side held
  bool beyond_validated_depth = false;// walked past kValidatedDepth
  bool crossed_at_entry = false;
};

// Levels the vendor reference constrains (book_snapshot_25). Not a limit on the walk -- a limit on
// what can be *claimed* about it.
inline constexpr std::size_t kValidatedDepth = 25;

// Throws std::invalid_argument for a non-finite or non-positive quantity.
Fill simulate_market_order(const OrderBook& book, OrderSide side, double quantity);
```

**Both slippage measures, because they answer different questions.** Against the far touch is the
cost of *size* alone — what walking past the first level cost. Against the mid includes the
half-spread, which is what a round trip actually pays. The impact literature usually regresses on
mid; the spread is a separate cost component that M7 must not double-count. Reporting both costs one
subtraction and prevents M5 from having to reconstruct either.

**No fees here.** M4 is slippage and impact only. Fees are a swept parameter (OD-11, resolved) and
enter at M7-T4. A fee constant appearing anywhere in this file is a bug.

**Where it lives.** `cpp/include/perpcarry/impact_simulator.hpp` + `cpp/src/impact_simulator.cpp`,
in `perpcarry_core`: pure, single-threaded, no file I/O. It reads `OrderBook::levels()` through the
zero-copy span — the one caller that span exists for (M2-T1 wrote it for exactly this).

## Data

Input: an `OrderBook` and an order. Output: a `Fill`. No corpus access, no files, no timestamps —
the time dimension is M4-T2's.

## Invariants this task must not break

**Calibrated, not assumed.** This *is* the calibration input. There is no constant in this file that
stands in for a market measurement.

**Determinism.** A pure function of book state and order (test 12), and it takes the book by const
reference — simulating must not consume the book, since M5 will simulate many sizes against the same
instant.

**Honest limitations.** `beyond_validated_depth`, `exhausted_book` and `crossed_at_entry` exist so
the three approximations in play are reported per-fill rather than described once in a document
nobody reads next to the number.

## Out of scope

- Time-sliced execution — **M4-T2**.
- Expressing size as a fraction of ADV or depth — **M4-T3**.
- Fitting an impact model to these fills — **M5**.
- Fees, funding, and settlement — **M7-T4** (OD-11).
- Resting limit orders and queue position — impossible on L2 data (D-017), not deferred.

## Open questions

**Q1 — should a crossed book refuse to simulate rather than reporting a flag?**
Recommendation: report the flag. Refusing would drop 6.3% of a real day's instants on a rule chosen
before seeing whether crossed-book fills are actually anomalous, and the flag lets M5 answer that
empirically. Revisit if the fills there turn out to be wild.

**Q2 — should the walk round quantities to `step_size` from `symbol_meta.json`?**
Recommendation: no, not in the core. The core has no symbol identity and reading committed metadata
into `perpcarry_core` would give it a data dependency it has carefully avoided. If sizes need
rounding, M4-T3 is where symbols exist and it can round before calling.

**Q3 — report the full per-level breakdown, or just the aggregate?**
Recommendation: aggregate plus `levels_consumed` and `worst_price`. A per-level vector would
allocate on every call, and M5 fits on aggregates. M2-T3's `dump_csv` already covers the case where
someone needs to see the levels a walk crossed.
