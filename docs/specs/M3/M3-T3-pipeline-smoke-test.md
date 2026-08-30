# M3-T3 — End-to-end pipeline smoke test

**Milestone:** M3
**Status:** **Complete 2026-08-29.** `cpp/include/perpcarry/pipeline.hpp` + `cpp/src/pipeline.cpp`,
bound as `Pipeline`; `python/perpcarry/tools/run_pipeline.py`; `tests/test_pipeline.py` (6 cases)
and `tests/tools/test_run_pipeline.py` (5). Real run recorded in
`docs/validation/M3-T3-0GUSDT-2026-06-01.json`. Two deviations, both below: `dump_csv` had to be
bound to Python after all, and the pipeline lives in `perpcarry_core` rather than `tools/`.
**Depends on:** M3-T1, M3-T2 (both complete 2026-08-29)
**Design doc:** Section 4, Section 5 (M3)

## Goal

Run one day of real book data through the whole assembled pipeline — Parquet on disk → PyArrow batch
→ pybind11 boundary → `BookReplayer` → `SPSCQueue` → consumer — and show the far end agrees with what
M2 already established. This is the task that turns four separately-tested components into a thing
that works, and it is the last piece of the "M0–M4 alone is a complete systems artifact" claim.

## Acceptance criteria

Copied verbatim from the design doc Section 5 table:

> Completes without error; final state matches M2-T2 checkpoint

**"M2-T2 checkpoint" names an artifact that does not exist, and this spec has to define it.**
Grepped 2026-08-29: `checkpoint` appears nowhere in the repository outside the design doc's own two
sentences. M2-T2 produces an aggregated JSON summary — counts, verdict, sampled timestamps — and
never serialises book state. Left undefined, this criterion gets discharged against whatever is
convenient at implementation time, which is how a criterion becomes a formality.

**The checkpoint, defined.** Two parts, both already available and both publishable:

1. **The committed M2-T2 JSON summary** for the same symbol-day (`docs/validation/`). The pipeline's
   run must reproduce its counts: `events`, `images`, `unambiguous_images`, and the `pass` verdict.
2. **A SHA-256 of `dump_csv(final_book, depth=25)`** — M2-T3's dump, which is a pure, deterministic,
   locale-independent function of book state, so the digest is stable across runs and machines.

Part 2 is the exact-state half, and the hash is what makes it committable: a digest exposes no
levels and cannot reconstruct a book, so it clears Tardis Clause 9.2(2) where the dump itself
plainly would not. Nobody has connected M2-T3's dump to this criterion before; it is the natural fit
and it removes the only reason this criterion was vague.

Expanded into checkable tests:

| # | Test | Where |
|---|---|---|
| 1 | The pipeline runs a **synthetic** day end to end, producer and consumer on separate threads, and completes without error | `tests/test_pipeline.py` |
| 2 | Consumer sees every event exactly once, in order — the queue is exercised, not bypassed | same |
| 3 | Final book state from the threaded pipeline equals the state from a single-threaded replay of the same input. Threading changes timing, never results (D-020) | same |
| 4 | Re-running the same input produces the identical `dump_csv` digest | same |
| 5 | The queue actually filled at some point during the run — a pipeline whose queue was never contended has not tested the thing it exists to test (C15) | same |
| 6 | An exception raised on the producer thread surfaces to the caller rather than hanging the consumer or being swallowed | same |
| 7 | **Real-data run**, local, not CI: `0GUSDT` 2026-06-01 reproduces the committed M2-T2 counts and its recorded digest | `docs/validation/M3-T3-0GUSDT-2026-06-01.json` |

**Done 2026-08-29.** `0GUSDT` 2026-06-01: **1,299,113 events in ~3.5s**, exactly the count M2-T2
recorded for the same day, so the checkpoint's first half matches. The queue saturated — peak
occupancy 65,536 of 65,536, with 160,255 producer stalls — so the contention this task exists to
exercise genuinely happened on real data, not only in the synthetic test.

The digest `e35d9045…cc4b3c0e` was identical across three runs **and** across a queue capacity of 8
versus 65,536, which changes the interleaving drastically (439,648 stalls against 160,255). That is
D-020's determinism property demonstrated on a real day rather than argued.

One independent cross-check worth recording: the final book is 400 bid / 998 ask levels, which is
exactly what M2-T3's "close" ladder sample reported at 23:59:59.598 for the same day, by a different
code path.

**Test 5 is the C15 guard for this task.** The obvious failure is a pipeline where the consumer keeps
up so easily that the queue is always empty — everything passes, and the concurrency was never
exercised. Assert observed occupancy went above zero.

**Test 3 is the one that would catch a real regression.** If threading changed the result at all, the
number it changed would be a fill price, and nothing downstream could tell.

**Two deviations from this spec as drafted.**

*`dump_csv` is bound to Python after all*, reversing M2-T3's "and probably never". That call
reasoned Python can read the corpus directly — true, and beside the point: this checkpoint is a
digest of the **replayed** book, which only C++ holds. The alternative was re-deriving the canonical
rendering in Python, where `repr(float)` and `std::to_chars` happen to agree today; a second source
of truth that agrees by coincidence is exactly what C15 warns is invisible until it stops.

*The threaded pipeline lives in `perpcarry_core`, not `tools/`.* It does no file I/O, so D-012 does
not exclude it, and the bindings link only the core. It is the sole threaded component there, and
the book core is still not concurrent: the `OrderBook` is owned entirely by the consumer thread and
the producer never sees it.

**Two tests added beyond the seven above:** a replay error injected 30,000 rows into a run with an
8-slot queue — the case that deadlocks if the consumer forgets to tell the producer it has stopped,
and a hang is a worse failure than an exception because it carries no message — and, on the Python
side, a per-field assertion that every Arrow column lands in the right `BookUpdate` field. A
transposed column mapping yields a run that completes, reports the right event count, and builds an
entirely wrong book; no count check in this project would notice.

## The licence and disk constraints, which shape the split

**Book data may never reach CI**, so tests 1–6 run on synthetic input, as every M2 test does. Only
test 7 touches vendor data, and it is local.

**A full day does not necessarily fit.** `export_book.py` records that a full `BTCUSDT` day is 161M
events and ~15 GB of CSV, against 20 GB free on this machine — which is why the committed BTCUSDT
validation summary covers ~12% of the day. This pipeline reads Parquet rather than CSV, so it avoids
the CSV blow-up entirely; the constraint to check before running is memory, since D-012's stated cost
is that batch size sets peak memory. Use `0GUSDT` 2026-06-01 (1.3M events) as the routine real run
and treat a full `BTCUSDT` day as an M10 scale question.

## Design

Producer thread: read the day's Parquet partition with `storage.py`, iterate batches, push
`BookUpdate`s onto the `SPSCQueue`. Consumer thread: pop, apply through `BookReplayer`, and at the end
dump the book and hash it.

**Reuse, do not restate (C15).** The partition layout comes from `storage.py`, the column order from
`export_book.py`'s `EVENT_COLUMNS`, the digest from M2-T3's `dump_csv`, and the expected counts from
the committed M2-T2 JSON. Every one of those is a value this test needs to know and the code already
owns; a restated copy is a second source of truth that can only agree by luck.

**Where the pybind boundary sits.** Batches cross once each, never per event (Risk R4). The queue is
on the C++ side of the boundary, between replay and simulation — not between Python and C++.

## Data

Input: `data/book/symbol=.../date=.../` Parquet (gitignored, re-derivable via M1). Output: a JSON
summary under `docs/validation/` carrying counts and the digest — no levels, no rows.

## Invariants this task must not break

**Determinism.** Tests 3 and 4. This is the first task where two threads touch the research path, and
therefore the first where determinism could be lost by accident rather than by design.

**Honest limitations.** The run covers one thin symbol-day. Say which day, and do not let "end-to-end
pipeline validated" stand unqualified in the writeup.

## Out of scope

- The impact simulator in the pipeline — **M4**; the consumer here applies updates, it does not
  simulate orders.
- Performance numbers — **M10-T1**. Completing is the criterion here, not completing quickly.
- Multi-day or multi-symbol runs — **M8**.

## Open questions

**Q1 — real second thread, or a coroutine? Taken: a real thread.**
Recommendation: a real thread. The point of M3-T2 is a boundary between two threads; a single-threaded
driver would test the queue's algebra and none of its memory ordering.

**Q2 — commit the digest, or recompute at run time? Taken: commit it.**
Recommendation: commit it. A digest recomputed from the same run proves nothing (C13's trap in a new
costume); a committed one from a dated run turns a future divergence into a failure. It exposes
nothing — that is the point of hashing it.

**Q3 — also assert against `book_snapshot_25` images? Taken: no.**
Recommendation: no. That comparison is M2-T2's, it is done, and repeating it here would make this
task's failures ambiguous between "the pipeline is wrong" and "the replay is wrong". Match the
checkpoint; let M2-T2 own the vendor comparison.
