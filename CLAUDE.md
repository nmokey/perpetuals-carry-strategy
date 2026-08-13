# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current state

Milestone **M0 (scaffolding) is complete**; M1 onward is unimplemented. What exists is the build system, the Python package skeleton, the Parquet I/O layer (M0-T4), and a stub C++ core whose only job is to prove the toolchain works end to end. `cpp/` contains a `version()` function and nothing else — `OrderBook`, `BookReplayer`, `SPSCQueue`, and the impact simulator are all still to be written (M2–M4), as are all the `python/perpcarry/{ingestion,models,strategy,reporting}` modules.

## Commands

```bash
uv sync                                # env + build extension (first run creates .venv)
uv run pytest                          # Python suite
uv run pytest tests/test_storage.py    # single file
uv run pytest -k round_trip            # single test by name
uv run ruff check . && uv run ruff format .

uv sync --reinstall-package perpcarry  # rebuild perpcarry_cpp after editing cpp/

uv run cmake -S . -B build/dev -G Ninja        # standalone C++ build
uv run cmake --build build/dev
uv run ctest --test-dir build/dev --output-on-failure
uv run ctest --test-dir build/dev -R smoke     # single C++ test by name
```

Toolchain notes worth knowing before debugging a build:

- CMake and Ninja are **dev dependencies inside `.venv`**, not system installs — hence the `uv run` prefix on every CMake command.
- scikit-build-core's editable rebuild-on-import is deliberately **off** (`editable.rebuild = false` in `pyproject.toml`). Its CMake cache points into the ephemeral build-isolation environment, which uv tears down after the sync, so imports fail with a stale ninja path. Rebuild explicitly instead.
- The standalone (non-wheel) CMake build finds pybind11 by shelling out to `python -m pybind11 --cmakedir` against the active interpreter; outside the venv it silently skips the extension module and builds only the core plus tests.
- Catch2 v3.7.1 is pulled at configure time via `FetchContent`, so the first configure needs network access.
- Python is pinned to 3.12 (`.python-version`) for wheel coverage; the project declares `>=3.11`.

## Working from the design doc

`docs/design-doc.md` is the source of truth for scope, architecture, and sequencing. It is explicitly a **seed document for spec-driven development**: each task in Section 5 (M0-T1, M1-T3, …) is intended to become one implementation spec/ticket.

Two rules follow from this:

1. **Check the task's dependencies before implementing.** Section 5 tables list `Depends On` for every task, and several tasks are blocked on an *open design decision* (bolded, e.g. "**OD-2 resolved**"). If you are asked to implement a task whose blocking OD is still `OPEN` in Section 6, surface that first — each OD has a documented recommendation/default that can be adopted, but the choice should be explicit, and the doc's Status line updated when it is made.
2. **Acceptance criteria are the spec.** Each task row states a concrete acceptance criterion (e.g. "no gaps in `trade_id` sequence", "withholding future data does not change historical outputs"). Implement against those, and add the test the criterion implies.

Known gaps in the doc, worth resolving as the affected milestones come up rather than silently working around:

- **No C++-side Parquet reader is specified.** Section 2 has the C++ core consuming the Parquet that Python writes, but Section 10's tech stack lists no Arrow C++ / Parquet dependency. Either add Arrow C++ at M2/M3, or have Python feed the replayer through the pybind11 boundary (which fits the pipeline-level-boundary rule better).
- **Section 3.2's book schema assumes diffs** (`update_id` sequence numbers), which only exist under OD-2 options (a)/(b). The recommended interim option (c), partial-depth snapshots, has no diff stream, so a snapshot-only path needs its own schema and a `BookReplayer` mode that ingests snapshots directly.
- **A few dependency edges are tighter than necessary**: M2-T1 (a pure data structure) depends on M1-T4 (full data QA), and M4-T2 (time-sliced simulator) depends on M3-T2 (SPSC queue). Both can be developed and unit-tested against synthetic fixtures earlier; the dependency is real only for the validation-against-real-data half of the acceptance criteria.
- **M7-T4 (fee/funding settlement accounting) sits after M7-T3 (backtest loop)**, though the loop's P&L needs it. Expect to build a minimal settlement model with T3 and refine it in T4.
- **M1-T1's "no gaps in `trade_id`"** is venue-specific — on Binance aggTrades, IDs are aggregated and gaps are expected by design. Validate against the raw trade endpoint or relax the criterion to monotonicity.

The highest-risk unresolved decision is **OD-2** (historical L2 order book data acquisition) — it gates M1-T3 and everything downstream. The doc's recommendation is to start with free partial-depth snapshots to unblock M2+, while recording live websocket depth-diffs in parallel for a later higher-fidelity pass.

## Planned architecture

Split by *what kind of correctness matters*, not by convenience:

- **C++ core (`perpcarry_cpp`)** — deterministic, single-threaded, unit-testable logic: `OrderBook` (L2 price-level state), `BookReplayer` (snapshot + sequential diff replay), `ImpactSimulator` (walks the book to compute realized fill price / slippage).
- **Concurrency is deliberately narrow** (OD-6): a lock-free `SPSCQueue<T>` decouples the ingestion/replay thread from the simulation thread, mirroring a real feed-handler → strategy-engine boundary. The book itself stays single-threaded. Do not add concurrency to the book core — a backtest has no real concurrent writers, and the doc rejects that explicitly.
- **pybind11 boundary sits at the pipeline level**, post-SPSC-queue — never per-tick. This is Risk R4: per-tick interop would undermine the latency story. Keep it that way when designing bindings.
- **Python research layer** owns everything statistical: impact model calibration (regression), funding persistence (Bayesian AR(1)), strategy/sizing decisions, walk-forward backtest, reporting.
- **Storage** is partitioned Parquet on local disk (`symbol=.../date=...`) via PyArrow, read with PyArrow/Polars; DuckDB is an optional ad hoc SQL layer over those files. No database server.

Data schemas for trades, L2 book updates, and funding rates are in Section 3 of the design doc — match those field names and types.

## Invariants worth protecting

These are the project's actual research claims; code that violates them makes the output worthless rather than merely wrong.

- **No look-ahead.** The funding model updates strictly rolling/online, and the backtest is walk-forward with rolling re-calibration (OD-12). M7-T3 requires a "future data poisoning" test: perturbing or withholding future data must not change historical outputs. Any new model or feature needs to hold that line.
- **Determinism / reproducibility.** Calibration dataset generation and the backtest must be reproducible given a fixed seed.
- **Impact costs are calibrated, not assumed.** The whole point is that the execution cost model is fit from real book data and then *drives* the entry threshold and position sizing. Never substitute a flat assumed transaction cost in the main path — the flat-cost version exists only as the M8-T4 naive baseline for comparison.
- **Honest limitations over flattering numbers.** The deliverable is a capacity answer, not a nice equity curve. Approximations (partial-depth book, frictionless spot leg per OD-4) get stated explicitly in output and writeup, not smoothed over. A "the edge doesn't survive costs" result is a valid outcome (Risk R2).

## Layout and tooling

Per OD-13/OD-14 and Sections 9/10 of the design doc:

- `cpp/{include/perpcarry,src,bindings,tests}` — C++20, CMake, pybind11, Catch2. ThreadSanitizer is still to be wired up for the M3-T2 queue stress test.
- `python/perpcarry/{ingestion,models,strategy,reporting}` — the wheel packages this directory; `tests/` at the repo root is the pytest suite mirroring it.
- `data/` is gitignored; everything under it is re-derivable from the M1 ingestion scripts. `PERPCARRY_DATA_ROOT` overrides the location.
- Bayesian inference on the critical path should be hand-rolled closed-form conjugate updating (Normal-Inverse-Gamma); PyMC/MCMC is an optional M9 addendum only (OD-8), which is why PyMC is not a dependency.

Two import names, easy to confuse: `perpcarry` is the pure-Python package under `python/`; `perpcarry_cpp` is the compiled extension, installed as a **top-level** module (not nested inside `perpcarry`) to match the M3-T1 acceptance criterion.

## Milestone sequencing

M0 → M1 (data) → M2 (C++ book) → M3 (bindings + SPSC) → M4 (impact simulator) → M5 (calibration) → M6 (funding model) → M7 (strategy + backtest) → M8 (comparative study) → M9 (writeup) → M10 (perf, stretch).

The ordering is intentional (Risk R3): M0–M4 alone is a complete systems artifact, M7 a complete research pipeline, M9 a polished writeup. Prefer finishing a milestone to starting the next one.
