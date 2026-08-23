# M2-T1 — Core price-level data structure

**Milestone:** M2
**Status:** **Complete 2026-08-22.** `cpp/include/perpcarry/order_book.hpp` +
`cpp/src/order_book.cpp`; 14 Catch2 tests, 10 mutations run and 9 caught — the survivor is the
`reserve()` call, which by construction has no observable behaviour (see Q1). Two deviations from this spec as
drafted, both recorded below: `depth()` was renamed `level_count()` (Q3, taken), and `BookUpdate`
was deferred to M2-T2 rather than landing here.
**Depends on:** M1-T4 (complete 2026-08-20), OD-5 (**resolved 2026-08-22** — L2, D-017)
**Design doc:** Section 3.2, Section 4.2, Section 5 (M2), OD-5

## Goal

`OrderBook` — the L2 price-level state that every downstream number is computed from. M4's impact
simulator walks this structure to produce a realized fill price, and that fill price is what makes
the project's central claim ("execution costs are calibrated, not assumed") either true or
decorative. A book that is subtly wrong yields a slippage figure that looks entirely plausible and
is not, with nothing downstream able to detect it. So the correctness bar here is agreement with an
*independent* implementation over a randomised event stream, not "the cases I thought to test pass".

## Acceptance criteria

Copied verbatim from the design doc Section 5 table:

> Unit tests cover top-of-book and deep-level updates; matches independently-reconstructed
> reference book on a sample window

**What "independently-reconstructed reference" means at T1.** The vendor's `book_snapshot_25` is
M2-T2's oracle and needs replay sequencing that does not exist yet. Here the independent reference
is a deliberately naive `std::map`-based book written inside the test file, and the "sample window"
is a seeded pseudo-random event stream. Two implementations of the same specification, compared
step by step — the value is that they fail differently. Agreement with real vendor data is T2's
criterion, not this one, and the spec does not pretend otherwise.

Expanded into checkable tests:

| # | Test | Where |
|---|---|---|
| 1 | Empty book returns no best bid and no best ask (not a zero, not a sentinel price) | `cpp/tests/test_order_book.cpp` |
| 2 | Add at a better price moves top-of-book; add at a worse price does not | same |
| 3 | Deep-level insert (level ~500) leaves best bid/ask and their quantities unchanged | same |
| 4 | `quantity == 0` removes the level | same |
| 5 | `quantity == 0` at a price not in the book is a no-op, not an error | same |
| 6 | Re-adding a previously removed price restores it at the correct rank | same |
| 7 | Same price with a new quantity replaces in place — no duplicate level, depth unchanged | same |
| 8 | `levels(side)` is ordered best→worst: bids descending, asks ascending, for both sides | same |
| 9 | `clear()` empties both sides; a subsequent add lands in an empty book | same |
| 10 | **Differential:** 100k seeded random operations against the in-test `std::map` oracle; both sides' full level vectors compared exactly (`price` and `quantity` bitwise) every operation | same |
| 11 | Add-then-remove at `0.4191` (not exactly representable in binary) round-trips — depth returns to zero | same |
| 12 | A crossed book is representable and reported by `is_crossed()`, not silently repaired | same |
| 13 | Non-finite price, non-positive price, or negative quantity is rejected | same |
| 14 | Determinism: the differential run repeated with the same seed produces the identical final state | same |

Test 5 is not hypothetical: **BTCUSDT 2026-06-01's opening snapshot block contains 13 zero-quantity
rows** (measured 2026-08-22). A book that treats a removal of an absent level as an error cannot
ingest the first 2,015 rows of a real day.

Test 10 is the criterion. Tests 1–9 exist so that when it fails, the failure has a name.

## Design

**Sorted `std::vector<Level>` per side.** Measured on the corpus (2026-08-22): the opening snapshot
holds 1,013 bid / 1,002 ask levels for `BTCUSDT` and 403 / 1,000 for `0GUSDT` — the feed caps
around 1,000 levels per side. At that size a side is ~16 KB of contiguous `{double, double}`, which
sits in L2 and is walked linearly by exactly the operation M4 performs on every simulated order.
Binary search plus a `memmove` on insert beats pointer-chasing at n≈1,000, and top-of-book is
`front()`.

Rejected, with reasons:

- **`std::map<double, double>`** — a node and a pointer chase per level, so M4's book walk touches
  1,000 scattered allocations per order. It is the right *oracle* (obviously correct, structurally
  different) and the wrong implementation.
- **Hash map + separately maintained sorted index** — two structures to keep in agreement, for no
  gain at this size; the extra state is a second thing that can be wrong.
- **Flat array indexed by tick** — genuinely attractive for speed, and `symbol_meta.json` already
  supplies the tick. It needs a price-window policy (what happens when the market moves out of the
  array) and it ties the core to a per-symbol constant. Revisit under M10 if profiling asks for it;
  deciding on a guess now is D-012's mistake in a different costume.

**Price is `double`, matching §3.2 — and that is safe here specifically because prices are only
ever compared, never derived.** The usual argument for integer-tick keys is that float arithmetic
makes equality unreliable; no arithmetic is ever performed on a key. A price parsed from the same
decimal text yields the same double, so add/remove pairing is exact (test 11 pins it). M4 does
arithmetic on prices *read out of* the book, which is a different operation on a value, not a key.

**Crossed books are reported, never corrected.** An aggregated L2 feed can transiently show
`best_bid >= best_ask` when updates for the two sides arrive out of order. Repairing it silently
would erase the single cheapest signal that a replay has gone wrong (C14: state the invariant, let
it catch what it catches). The book exposes `is_crossed()`; M2-T2 counts occurrences per day.

### Interface — the contract M2-T2, M3-T1 and M4-T1 build on

```cpp
namespace perpcarry {

enum class Side : std::uint8_t { Bid = 0, Ask = 1 };

struct Level {
  double price;
  double quantity;
};

class OrderBook {
 public:
  static constexpr std::size_t kInitialLevelCapacity = 2048;

  OrderBook();

  void apply(Side side, double price, double quantity);  // quantity == 0 removes
  void clear();

  std::optional<Level> best(Side side) const;
  std::optional<Level> best_bid() const;
  std::optional<Level> best_ask() const;
  bool is_crossed() const;

  std::size_t level_count(Side side) const;
  std::span<const Level> levels(Side side) const;  // best → worst
};

}  // namespace perpcarry
```

**`BookUpdate` is not here — it lands in M2-T2 (deviation from this spec as drafted).** The draft
listed it in this block because it is part of the same contract, but nothing in T1 consumes it: its
`timestamp` and `is_snapshot` fields are sequencing concerns this spec explicitly assigns to the
replayer. Shipping an unused struct in T1 would be implementing ahead of the milestone (C5) and
would freeze a layout before the code that reads it exists.

`levels()` returning a `span` over contiguous storage is deliberate: it is what M4-T1 iterates, and
it means the book walk needs no copy and no allocation. That also fixes the storage choice as part
of the contract, so it is stated here rather than left as an implementation detail.

`clear()` keeps capacity (`reserve` at a named constant, 2048 per side) so steady-state replay
after warmup performs no allocation. Resyncs happen ~13 times a day, so this matters less than it
sounds; it costs one line and removes a source of timing noise from any M10 measurement.

## Data

No file I/O and no storage dependency at all (D-012). Input is `BookUpdate` values constructed by
the caller. Every fixture in this task is synthetic — required by the Tardis licence for anything
committed, and sufficient, since the vendor comparison belongs to T2.

The §3.2 fields this class consumes are `side`, `price`, `quantity`. `timestamp` and `is_snapshot`
are sequencing concerns and belong to `BookReplayer` — the book is a pure state machine with no
notion of time, which is what makes the differential test possible.

## Invariants this task must not break

**Determinism.** No clock, no RNG, no ordering that depends on address or hash. The differential
test's RNG is seeded and its seed is committed; test 14 asserts a repeat run is identical. This is
the level at which the project's reproducibility claim is cheapest to guarantee and most expensive
to lose.

**No look-ahead.** Structural here rather than tested: the book applies one update at a time and
holds no future state. It cannot look ahead because it cannot see anything but the update in hand.
Recorded so it is not left unaddressed — the substantive look-ahead tests belong to M6/M7.

**Stated approximations.** L2 aggregation (D-017) means queue position is unknowable. This class
therefore cannot support any claim about resting-order fill probability, and M4 must not grow one
on top of it. That limitation goes in the M9 caveats.

## Out of scope

- Snapshot/diff sequencing and resync handling — **M2-T2**.
- Dump / human-readable rendering / structured diff — **M2-T3**.
- Any Python access — **M3-T1**. Nothing in this task is exposed through `perpcarry_cpp`.
- Book walking, fills, slippage — **M4-T1**.
- Cumulative-depth or ADV normalisation — **M4-T3**.

## Open questions

**Q1 — is the reserve capacity worth exposing as a constructor parameter? — TAKEN: no.**
`kInitialLevelCapacity = 2048`, hardcoded, with the measurement cited in a comment. A knob with one
caller is a knob nobody tunes correctly; M10 can add one with a profile to justify the value.

**This is the one line in the file no test covers, and deliberately so.** `reserve()` changes when
allocation happens, not what the book contains, so every mutation of it survives the suite —
verified, not assumed. Asserting on `capacity()` would pin an implementation detail and fail the
moment the container changed. Recorded here rather than left as a silent gap in the mutation count.

**Q2 — should the book maintain a running cumulative quantity for M4-T3's "% of top-N depth"?**
Recommendation: no. Compute it on demand in M4 by walking the span. A maintained running sum is a
second piece of state that must stay correct across every add, modify and remove, in service of a
consumer that does not exist yet (C5).

**Q3 — "depth" is overloaded — TAKEN: renamed to `level_count()`.** M4-T3's depth is a quantity;
this one is a count of levels, and the two would have collided across the pybind11 surface. Renamed
now rather than after M3-T1 freezes the binding names.
