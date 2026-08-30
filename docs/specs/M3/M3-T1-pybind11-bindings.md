# M3-T1 — pybind11 bindings

**Milestone:** M3
**Status:** **Complete 2026-08-29.** `cpp/bindings/pybind_module.cpp` + `tests/test_bindings.py`;
17 test items, 6 mutations run and 6 caught — after one survived (see below). Four deviations from
this spec as drafted, all recorded in place: `Level` is not bound as a class (Q1 taken — levels and
best cross as `(price, quantity)` tuples, so no `Level` type is needed on the Python side); four
tests were added beyond the nine below; `BookReplayError` is registered as its own Python exception
type; and the PyArrow→`BookUpdate` conversion is deferred to M3-T3, where it has a consumer, rather
than landing here speculatively.
**Depends on:** M2-T2 (complete 2026-08-29). No open design decision gates this task.
**Design doc:** Section 4.4, Section 5 (M3), Risk R4

## Goal

Make the C++ core callable from the Python research layer, so M5's impact calibration and M7's
backtest can replay a book and read its state without shelling out to a tool. The boundary is the
pipeline, never the tick (Risk R4).

**What this task is no longer for, and the spec has to say so.** The design doc's criterion — "book
state queried from Python matches C++ fixture tests" — was written when the bindings were assumed to
be *how the book gets validated against vendor data*. That is no longer true. D-018 routed the whole
validation loop through `export_book.py` plus the `perpcarry_replay_validate` CSV harness, precisely
because M3-T1 depends on M2-T2 and could not be the validator for the thing it depends on. That loop
is closed, ran on real data, and is recorded in `docs/validation/`.

So the bindings are not on the validation path at all. They exist to feed M5 and later. A reader who
takes the doc's criterion at face value will rebuild the validation loop through pybind11 and
duplicate work that is already done and already green.

## Acceptance criteria

Copied verbatim from the design doc Section 5 table:

> Book state queried from Python matches C++ fixture tests

**Read carefully, this criterion invites the C15 trap.** If the Python test restates the same
fixture the C++ test uses, the two are one assumption written twice, and they agree by construction
rather than by evidence — exactly the failure that let `validate_data` report a healthy corpus while
looking in a directory that never existed. The book's *semantics* are already covered by 51 C++
tests, including a 100k-operation differential run against an independent `std::map` oracle. Nothing
is gained by re-asserting them through a second language.

**What the Python tests are actually for: the boundary is faithful.** Ordering survives, depth
truncation survives, types convert, lifetimes are safe, and errors cross as exceptions rather than
as crashes or silent zeros. Those are properties of the binding layer, and no C++ test can see them.

Expanded into checkable tests:

| # | Test | Where |
|---|---|---|
| 1 | `perpcarry_cpp` imports as a **top-level** module, not nested under `perpcarry` | `tests/test_import.py` (exists) |
| 2 | A book built through the Python API reports the same `best_bid`/`best_ask`/`level_count`/`is_crossed` as the equivalent C++ fixture — values taken from the C++ test's own constants, not retyped | `tests/test_bindings.py` |
| 3 | `levels(side)` comes back best→worst on both sides, as a Python sequence of `(price, quantity)` | same |
| 4 | Prices survive the round trip bit-exactly, including `0.4191` and a value needing 17 significant digits — a float that changes crossing the boundary makes every downstream number wrong quietly | same |
| 5 | **Lifetime:** a `levels()` result taken before an `apply()` is still valid and unchanged after it (see Design — the C++ span is invalidated, so the binding must copy) | same |
| 6 | An invalid update (non-finite price, negative quantity) raises a Python exception, not a crash and not a silently ignored call | same |
| 7 | `BookReplayer` replays a batch handed over as one call, and its `stats()` cross correctly | same |
| 8 | Replaying the same batch twice through Python gives the identical final state (determinism survives the boundary) | same |
| 9 | The module exposes **only** the documented surface — a test asserts the public symbol set, so a new binding is a deliberate act rather than a side effect | same |

Test 9 is cheap and pays out where it was not aimed (C14): every bound symbol is a compatibility
commitment, and the surface is much easier to keep small than to shrink later.

**Four tests added during implementation, three of them for things this spec did not anticipate:**

| # | Test | Why it was added |
|---|---|---|
| 10 | An empty book returns `None` from `best_bid`/`best_ask`, not a `(0.0, 0.0)` sentinel | A sentinel price crossing as "no bid" is a silently wrong number, and `std::optional` has no natural Python form until one is chosen |
| 11 | A book obtained from a `BookReplayer` stays valid after the replayer is dropped | **The second lifetime hazard, which this spec named only the first of.** `BookReplayer::book()` returns a C++ reference; bound with `return_value_policy::reference` rather than `reference_internal`, `book = r.book(); del r` reads freed memory |
| 12 | `BookReplayError` is catchable as its own type | A replay rejecting its input is a different situation from a bug in the caller, and M3-T3 needs to tell them apart |
| 13 | `BookReplayer` has **no** single-row `apply` on the Python side | Risk R4 as a regression guard rather than a comment — the per-row door is the tempting one |

**One mutation survived the first pass, and the gap it exposed was real.** Narrowing `levels()`'s
output to `float` passed the whole suite: test 4 asserted round-trip fidelity only through
`best_bid()`, and `levels()` is a *separate* emitting path — the one M5 actually walks for depth,
so the more important of the two. Test 4 now asserts through both. Test 11's mutation
(`reference_internal` → `reference`) segfaults deterministically at the line after `del`, which is
the strongest available signal that the keep-alive is doing work.

## Design

**What crosses, and nothing else.** `Side` (enum), `Level` (a `(price, quantity)` pair),
`BookUpdate`, `OrderBook`, `BookReplayer`. That is the minimum M5 needs to replay a window and read
depth out of it.

**What deliberately does not cross:**

- **The M2-T3 renderers** (`dump_csv`, `format_ladder`, `format_diff`, `format_price`). M2-T3 put
  this out of scope explicitly — "and probably never": the C++ dump is what the C++ harness needs,
  and Python can already read the corpus directly. Left unstated, they get bound simply because they
  are there.
- **`compare_top_n` / `BookDiff`.** Comparison against vendor images is the harness's job (D-018),
  and it lives on the other side of a licence boundary that Python-side code should not be invited
  across.

**The one real hazard, which the design doc does not mention.** `OrderBook::levels()` returns a
`std::span<const Level>` whose header states plainly that it is "invalidated by the next `apply()`
or `clear()`". That is correct and deliberate on the C++ side — it is what lets M4 walk the book
with no copy and no allocation. Exposed naively to Python it becomes a dangling view: the object
stays alive, keeps returning numbers, and the numbers are garbage after the next update. It fails as
a plausible slippage figure rather than as a crash, which is the worst available failure mode for
this project.

So the binding **copies** at the boundary — `levels()` returns a new Python list (or, if profiling
ever justifies it, a NumPy array owning its buffer). Test 5 exists to pin this and would fail on a
zero-copy binding written for speed. The zero-copy path stays available to C++ callers, which are
the ones that need it.

**Batch, never per-tick (Risk R4).** `BookReplayer` takes a sequence of updates in one call. There is
no `apply_one` on the Python side, and adding one would be the R4 mistake in its most tempting form.
`pybind_module.cpp` already carries this rule as a comment; this spec is where it becomes testable.

**Where the input comes from.** Python reads Parquet with PyArrow and hands over an in-memory batch;
the core takes rows, never a path (D-012). `storage.py` already does the reading, and
`export_book.py` already knows the column order — reuse both rather than restating the layout (C15).

## Data

Input: in-memory batches of book updates, columns as in design doc §3.2. Output: book state as
Python values. No files on either side of the boundary.

## Invariants this task must not break

**Determinism.** A float that changes crossing the boundary would corrupt every downstream number
while looking entirely plausible; tests 4 and 8 pin the value and the replay.

**No look-ahead.** Not in play at T1 — the bindings expose state, not a model.

**Honest limitations.** The interop cost is Risk R4's subject and must be *measured*, not asserted
away. M10-T1 records it; this task only has to avoid designing a per-tick boundary that would make
the number embarrassing.

## Out of scope

- Binding the impact simulator — **M4**, which does not exist yet.
- Rendering book state from Python — **M2-T3**, out of scope there and here.
- The end-to-end pipeline run — **M3-T3**.
- Interop benchmarking — **M10-T1**.

## Open questions

**Q1 — `levels()` as a list of tuples, or a NumPy array? Taken: list of tuples.**
Recommendation: list of tuples first. M5 consumes depth in Python-level code, the arrays are ~25–1000
rows, and NumPy in the signature is a dependency in the wheel's public API. Revisit if M10 shows the
conversion mattering; the test that pins the copy semantics does not care which is chosen.

**Q2 — expose `BookReplayer::Stats`? Taken: yes, as `ReplayStats`.**
Recommendation: yes. It is counts only, it is what M3-T3's smoke test asserts on, and it carries no
book data across the licence boundary.

**Q3 — should the batch entry point accept a PyArrow table directly? Taken: no.**
Recommendation: no, not yet. It would put Arrow's C++ headers into the build, which D-012 explicitly
avoided. Take a sequence of plain rows and let Python do the unpacking until a profile says otherwise.
