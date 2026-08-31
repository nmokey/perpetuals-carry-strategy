# M4-T2 — Time-sliced TWAP/VWAP simulator

**Milestone:** M4
**Status:** **Complete 2026-08-30.** `simulate_sliced_execution` in
`cpp/include/perpcarry/impact_simulator.hpp`; 13 Catch2 cases, 4 mutations run and 4 caught after
one survived. One decision this spec did not anticipate and had to make: **slices consume the
liquidity they take (D-023)**, which required `execute_market_order` and a `mutable_book()` on
`BookReplayer`. Two tests added beyond the ten below.
**Depends on:** M4-T1; M3-T2 (complete 2026-08-29 — the edge the watch list called over-tight is now
simply satisfied)
**Design doc:** Section 4.3, Section 5 (M4)

## Goal

`simulate_sliced_execution(...)` — execute one parent order as a schedule of child orders against a
book that *moves between them*, and report what the whole thing cost. This is what makes the
capacity answer about execution rather than about arithmetic: a size that is ruinous as one
market order may be affordable spread over ten minutes, and the difference between those two
numbers is the entire practical content of "how large can this strategy trade".

## Acceptance criteria

Copied verbatim from the design doc Section 5 table:

> On synthetic test book: slippage increases monotonically with size (fixed window), decreases with
> longer duration (fixed size)

**Read the second half carefully — it is only true if the book replenishes.** Slippage falls with
duration because liquidity returns between slices. On a synthetic book built to replenish, that
holds by construction and the test is really checking that the simulator *sees* the replenishment
rather than replaying against a frozen snapshot. On a real book it may not hold at all: over a
trending window, waiting costs more than it saves. **That is a finding, not a bug**, and the spec
says so now so that nobody later "fixes" the simulator until real data reproduces a synthetic
property.

Expanded into checkable tests:

| # | Test | Where |
|---|---|---|
| 1 | One slice over zero duration is identical, bit for bit, to `simulate_market_order` for the same size | `cpp/tests/test_impact_simulator.cpp` |
| 2 | **Criterion, size:** on a replenishing synthetic book with a fixed window, total slippage is non-decreasing across a sweep of sizes | same |
| 3 | **Criterion, duration:** on the same book with a fixed size, total slippage is non-increasing across a sweep of durations | same |
| 4 | The book actually evolves between slices: a schedule whose later slices meet replenished liquidity fills them better than a frozen-book replay of the same schedule | same |
| 5 | **No look-ahead:** a slice at time *t* fills identically whether or not updates after *t* are present in the input | same |
| 6 | Slice sizes sum to the parent size, and the last slice absorbs the rounding remainder rather than dropping it | same |
| 7 | A slice that exhausts the book reports it, and the parent order reports partial completion rather than an average price over a fill that never happened | same |
| 8 | Per-slice results are retained, so a parent fill can be attributed to the slice that caused it | same |
| 9 | Determinism: identical inputs give a bit-identical parent fill, and re-running does not depend on replay batch boundaries | same |
| 10 | A caller-supplied weight vector (VWAP-style) is honoured; equal weights reproduce TWAP exactly | same |

**Test 5 is the one that protects the research result.** Look-ahead leakage is ranked first among
the things that invalidate this work, and a time-sliced simulator over a replayed stream is the most
natural place in the whole project for it to enter — one loop written in the wrong order and every
slice fills against a book that already knows what happened next. It is cheap to test and
catastrophic to miss.

## What this spec got wrong, found by a test written for something else

The draft had each slice call M4-T1's `simulate_market_order`, which is read-only. Test 4 ("the book
really evolves between slices") then failed in a way that exposed the real problem: with a frozen
book, four slices of 5 units each saw *undepleted* liquidity and filled at the same average as one
slice of 5. A 20-unit parent order came out cheaper than a single 20-unit order, purely from being
labelled as four.

Fixed by **D-023**: slices consume. `execute_market_order` does the same walk and then depletes what
it took; `simulate_market_order` stays const, because M5 still needs to sweep many sizes against one
instant. A test pins both behaviours so neither can quietly become the other, and a second test pins
the invariant that motivated the change — splitting an order at one instant must not make it cheaper.

The approximation this introduces is stated in D-023 and belongs in the M9 caveats: a later vendor
update at a touched price carries an absolute quantity and overwrites the footprint, so our impact
decays as the real book refreshes. Crude, but taken from the data rather than assumed — and it is
what makes "spreading an order over time is cheaper" a measured effect here rather than a
construction.

## Measured on real data, 2026-08-30

The tests above run on synthetic books by necessity — vendor rows may not reach CI — so until
`cpp/tools/impact_probe.cpp` existed this task had **never touched real data at all**. It has now.
`0GUSDT` 2026-06-01, 40 sampled windows, each parent order worked over 10 s in 5 slices against
taking it at once:

| size (base units) | at once | worked over 10 s | slicing was cheaper |
|---|---|---|---|
| 100 | 1.50 bps | 1.59 bps | 52.5% |
| 1,000 | 2.37 | 1.83 | 65.0% |
| 10,000 | 6.10 | 3.81 | 87.5% |
| 50,000 | 13.77 | 8.17 | 95.0% |
| 200,000 | 39.95 | 20.97 | **100%** |
| 1,000,000 | 261.32 | 186.22 | **100%** |

**The criterion's second half holds on real data for large orders, and does not for small ones** —
exactly the caveat written above before any of this was measured. At 100 units slicing is *worse*
on average (1.59 against 1.50) and barely better than a coin flip on any given window: the order is
small enough that the spread and the mid's own drift dominate, and there is nothing to save by
waiting. By 200,000 units it is cheaper on every window sampled, and roughly halves the cost.

That is the shape a capacity study wants, and it is a finding rather than a fixture property: the
same monotonicity the synthetic book guarantees by construction turns out to be real where it
matters and absent where the order is too small for impact to be the dominant term.

## Design

**The simulator takes a schedule, not a policy.** TWAP and VWAP differ only in the weights; making
the caller supply them keeps the volume-profile question — which needs trades aligned to the book —
out of the C++ core and in M4-T3/M5 where the corpus lives.

```cpp
struct SliceSchedule {
  std::int64_t start_timestamp = 0;   // ms, matching the book feed (D-013)
  std::int64_t duration_ms = 0;       // 0 means a single immediate slice
  std::size_t slices = 1;
  std::vector<double> weights;        // empty == equal weights (TWAP)
};

struct SlicedFill {
  Fill parent;                        // aggregated, same shape as M4-T1's
  std::vector<Fill> slices;           // one per child order, in execution order
  std::size_t slices_exhausted = 0;
  bool completed = false;             // every slice filled its full requested size
};

SlicedFill simulate_sliced_execution(std::span<const BookUpdate> updates, OrderSide side,
                                     double total_quantity, const SliceSchedule& schedule);
```

**It owns a `BookReplayer` internally and advances it to each slice's timestamp.** That is the shape
D-012 already established — a batch in, no path, no file I/O — and it makes test 5 structural: the
replayer is advanced *only* to `slice_time`, so updates after it have not been applied and cannot
influence the fill. The alternative, handing the caller a stateful object to drive, moves the
look-ahead risk into every call site instead of containing it in one place.

**Slice timing.** Slice *i* of *n* executes at `start + duration_ms * i / n`, integer arithmetic, so
the first slice is at `start` and slices are evenly spaced. With `duration_ms == 0` every slice
executes at `start` against the same book, which is why test 1 can compare against the static walk.

**Weights and the remainder.** Child size is `total * weight[i] / sum(weights)`, and the final slice
takes `total - sum(previous)` rather than its own computed share. Otherwise floating-point division
loses or invents a sliver of the parent order, and a capacity study that silently trades 0.9999 of
what it claims is reporting the wrong number in the direction that flatters it.

**The queue is not in this path, and that is deliberate.** M3-T2's `SPSCQueue` decouples ingest from
replay in the *pipeline*; this simulator is a pure function over a batch. Putting a queue inside it
would add nondeterminism to the one component whose determinism the calibration depends on, for no
benefit — the design-doc edge on M3-T2 was about developing against real replayed data, which
`Pipeline` now provides, not about this function using a queue.

## Data

Input: a batch of `BookUpdate` (design doc §3.2), an order, and a schedule. Output: a `SlicedFill`.
No corpus access and no files; the caller reads Parquet and hands over rows, as M3-T3 does.

## Invariants this task must not break

**No look-ahead.** Test 5, and the structural argument above. This is the invariant most at risk in
this task and the one that most badly destroys the result.

**Determinism.** Test 9, including independence from how the caller batches its updates — a fill that
depended on batch boundaries would make the calibration dataset a function of the reader's chunk
size.

**Calibrated, not assumed.** No decay constant, no assumed replenishment rate, no participation-rate
heuristic. The book replenishes at whatever rate the data says it does; if a model of that is wanted
later, it is fitted in M5 from these outputs.

**Honest limitations.** Each slice carries M4-T1's `beyond_validated_depth` and `crossed_at_entry`,
and the parent reports how many slices were affected — a ten-slice order where two slices walked past
level 25 is a different claim from one where none did.

## Out of scope

- Choosing the schedule (a participation-rate or volume-profile policy) — **M4-T3 / M5**.
- Reacting to fills: adaptive or opportunistic execution. The schedule is fixed in advance, which is
  both simpler and honest about what L2 data can support.
- Market-impact *decay* modelling — **M5**, fitted rather than assumed.
- Fees and funding — **M7-T4**.

## Open questions

**Q1 — should a slice that exhausts the book roll its unfilled remainder into the next slice?**
Recommendation: no, not by default. Rolling forward is an execution *policy*, and the point of this
task is to measure what a stated schedule costs. Report the shortfall and let M5 or M7 decide.
Revisit if real sweeps exhaust the book often enough to make the unrolled result uninformative.

**Q2 — what happens when the book is crossed at a slice's timestamp?**
Recommendation: inherit M4-T1's behaviour exactly — walk it, flag it, count it at the parent level.
A second policy here would give the same condition two meanings in one milestone.

**Q3 — should slice timestamps snap to actual update timestamps rather than the arithmetic grid?**
Recommendation: no. The grid is what "TWAP over ten minutes" means, and snapping to the feed would
make the schedule depend on update density, which is itself a liquidity signal — quietly correlating
the schedule with the thing being measured.
