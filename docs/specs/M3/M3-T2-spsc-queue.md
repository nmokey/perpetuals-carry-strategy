# M3-T2 — Lock-free SPSC queue

**Milestone:** M3
**Status:** Draft
**Depends on:** M2-T2 (complete 2026-08-29); OD-6 (**resolved 2026-08-29** — option (b), D-020)
**Design doc:** Section 4.1, Section 5 (M3), OD-6, Risk R4

## Goal

`SPSCQueue<T>` — a bounded lock-free single-producer/single-consumer queue decoupling the
ingestion/replay thread from the simulation thread. It is the project's one piece of real
concurrency, and OD-6 chose it because the feed-handler → strategy-engine split is a structure that
exists in real systems, not because it makes a backtest faster.

**Say the honest version now, not at writeup (D-020).** In a backtest the producer is reading a
file. The queue is not on a latency-critical path in any live sense. The defensible claim is that
the structure mirrors a real boundary and that its throughput is measured; the indefensible one is
that it makes the backtest low-latency. Everything this task produces should be phrased so the
first claim is the one a reader takes away.

## Acceptance criteria

Copied verbatim from the design doc Section 5 table:

> Stress test: N million events, zero loss, no data race under ThreadSanitizer; throughput
> benchmark recorded

Expanded into checkable tests:

| # | Test | Where |
|---|---|---|
| 1 | Single-threaded: push to capacity, pop everything back, values and order identical | `cpp/tests/test_spsc_queue.cpp` |
| 2 | A full queue refuses the push and reports it; a empty queue reports empty. Neither blocks, neither overwrites | same |
| 3 | Wrap-around: capacity `N`, push/pop `10N` items one at a time, all values correct — the ring's index arithmetic is where off-by-ones live | same |
| 4 | **Stress:** 10M items through two real threads, consumer sees every value exactly once, in producer order, none lost, none duplicated | same |
| 5 | Same stress run under **ThreadSanitizer**, clean | CI job (see below) |
| 6 | Non-trivial `T` (a type with a non-default constructor and a destructor) is constructed and destroyed exactly once per item — no leak, no double-destroy | same |
| 7 | **Determinism (D-020):** the consumer's output is byte-identical across runs with the same input, despite different interleavings between runs | same |
| 8 | Throughput is recorded to `docs/validation/` as items/sec with hardware and build flags stated | `docs/validation/M3-T2-throughput.json` |

**Test 7 is the one that protects the research result, and it is the one most likely to be skipped.**
D-020 permits the queue to change *when* an item is consumed and forbids it changing *which* or *in
what order*. FIFO gives the ordering for free, so the whole risk sits in the consumer: any behaviour
that depends on queue occupancy, on how many items happen to be available in a batch, or on producer
timing makes results differ run to run on identical input. The test drives the same input through
with deliberately varied producer pacing and requires identical output. Reproducibility given a
fixed seed is a north-star invariant; this is where a queue would quietly take it away.

Test 4's "in producer order" is not redundant with test 1: a single-threaded test cannot observe a
missing release/acquire pair, because there is no second thread to observe staleness from.

## Design

Bounded ring buffer, capacity a power of two so the modulo is a mask. `head_` and `tail_` are
`std::atomic<std::size_t>` on separate cache lines — without the padding the two indices share a line
and the "lock-free" queue spends its time on coherence traffic, which is the classic way this
structure gets written and then benchmarks badly.

**Do not hard-code 64 for the padding.** Measured 2026-08-29 on this machine (Apple Silicon, clang,
C++20): `std::hardware_destructive_interference_size` is **256**, not 64. A fixed 64-byte pad — the
number every SPSC tutorial uses, because they were written for x86-64 — under-pads by 4x here and
reintroduces exactly the false sharing the padding exists to prevent, silently and only on the
development machine's architecture. Use the constant, guarded by
`__cpp_lib_hardware_interference_size` with a fallback for toolchains that lack it.

One consequence to expect rather than debug: GCC warns (`-Winterference-size`) when that constant is
used in a header, because its value can differ between translation units and it is therefore an ABI
hazard. `SPSCQueue` is header-only, so CI's Linux job will meet this. Decide deliberately — suppress
the warning for that header, or accept a fixed per-platform constant — and record which, rather than
discovering it as a build failure.

Producer: load `tail_` relaxed (it owns it), load `head_` acquire, store `tail_` release. Consumer
mirrors it. That is the whole synchronisation argument, and it is short on purpose — a queue whose
correctness needs a long argument is one that should not be hand-rolled.

`try_push` / `try_pop` return a bool. **No blocking, no spinning inside the queue**: what to do when
full is a policy the caller owns, and burying a spin loop in the data structure makes the throughput
number a measurement of the spin rather than of the queue.

**Header-only template** in `cpp/include/perpcarry/spsc_queue.hpp`. It is a template on `T`, so
there is nothing to put in a `.cpp`, and `perpcarry_core`'s source list stays a list of things with
definitions.

**Do not add concurrency to the book core.** Restated here because this is the task where the
temptation arrives: `OrderBook` and `BookReplayer` stay single-threaded and untouched. The queue sits
*between* replay and simulation; it does not reach into either.

## ThreadSanitizer — the blocker this task has to clear, not inherit

`blockers.md` records that **TSan is not wired into the build and there is no nightly CI tier**. The
acceptance criterion requires a TSan-clean run, so that build work is inside this task's scope. A
criterion that cannot be executed is not a criterion (the same reasoning that forced D-019).

Two things to get right:

- **A CMake option** (`PERPCARRY_SANITIZER=thread`) adding `-fsanitize=thread` to a build of the
  queue stress test. Not the whole suite: TSan slows execution by roughly an order of magnitude, and
  the only thing here with two threads is this test.
- **A CI job that actually runs it** (C10). The design doc specifies a nightly tier that does not
  exist, and "we ran TSan once locally" is a claim about the past, not a property of the branch. A
  queue stress test is seconds of work even under TSan, so it belongs in the per-PR tier where it can
  keep being true. Build it locally first and verify the exact command (C11).

Note one interaction with the current build: `cpp/tests/CMakeLists.txt` hard-errors when tests are on
and tools are off, deliberately, so a sanitizer configuration must either satisfy that or turn both
off explicitly.

## Data

None. No files, no corpus, no licence surface — this is the one M2/M3 task whose tests can be fully
public and fully in CI.

## Invariants this task must not break

**Determinism / reproducibility.** The whole subject of test 7 and of D-020. This is the invariant
most at risk from this task, and the risk comes from the consumer, not the queue.

**Honest limitations.** The throughput figure is recorded with hardware and build flags, and framed
as a property of the structure rather than as evidence the backtest is low-latency.

## Out of scope

- Wiring the queue into the real pipeline — **M3-T3**.
- MPMC, or any queue with more than one producer or consumer. There is one producer and one
  consumer, by construction; a general queue would be untested generality.
- Throughput comparison against `boost::lockfree` or `folly` — **M10**, if it earns its place.
- Making `OrderBook` thread-safe. Not out of scope so much as forbidden (OD-6/D-020).

## Open questions

**Q1 — capacity, and what happens when the producer outruns the consumer?**
Recommendation: 65,536 slots, and the caller spins-then-yields on a failed push. The number matters
less than that the policy is the caller's and is visible; make it a constructor argument so M3-T3 can
show the queue actually filling rather than being permanently empty.

**Q2 — `T` for the real pipeline: `BookUpdate`, or a replayed book snapshot?**
Recommendation: `BookUpdate`. It is trivially copyable and small, the producer already has it, and it
keeps the queue's element a value rather than a reference into a book that the other thread mutates.
Confirm at M3-T3, where the consumer's actual needs are visible.

**Q3 — record throughput in `docs/validation/` or in `progress.md`?**
Recommendation: both, as M2-T2 did — a JSON artifact for the number, a dated line for the fact that
it was measured. The JSON here carries no licence risk at all, unlike M2's.
