# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current state

Milestone **M0 is complete (T1–T6)**; M1 is specced but unimplemented. What exists is the build system, the Python package skeleton, the Parquet I/O layer (M0-T4), the download/extract helpers (M0-T6), and a stub C++ core whose only job is to prove the toolchain works end to end. `cpp/` contains a `version()` function and nothing else — `OrderBook`, `BookReplayer`, `SPSCQueue`, and the impact simulator are all still to be written (M2–M4), as are the `models/`, `strategy/`, and `reporting/` packages and every M1 fetcher.

**Data sourcing is settled** (D-009, and `docs/external-dependencies-audit.md`): Binance USD-M throughout — trades/funding/klines from the `data.binance.vision` S3 archive, L2 order book from the Tardis.dev free tier (first day of each month). **No venue API is used or usable** — `fapi.binance.com` and Bybit are geo-blocked from this location. Don't write code that calls one.

## Standing steering — read these first

`docs/` carries the state that persists across sessions. Treat them as instructions, not
background reading:

| File | What it is | When to touch it |
|---|---|---|
| `docs/conventions.md` | Accumulated lessons, C1–C12 | **Read before starting work; apply every rule.** Append a new entry whenever a lesson is learned or reversed |
| `docs/progress.md` | Dated log of what was verified | Add a dated entry (`YYYY-MM-DD`, newest first) as part of finishing work — not as a later cleanup pass |
| `docs/blockers.md` | What's blocked, and the interim path | Check before starting a milestone; log new blockers as they appear |
| `docs/decisions.md` | OD-N resolution status + D-NNN build decisions | Log any decision the design doc didn't specify; when resolving an OD, update the design doc's Status line too |
| `docs/north_star.md` | The research question and what invalidates it | Consult when a tradeoff feels ambiguous; rarely edited |
| `docs/specs/` | One spec per Section 5 task, `M<n>/<TASK-ID>-<slug>.md` | Write just-in-time from `TEMPLATE.md`, at most one milestone ahead |

Two of those conventions govern how this session operates and are worth restating here:

- **C1 — never take a remote action without explicit approval.** No push, PR, issue, tag, release, or write to any external service without asking and getting a yes. Read-only remote calls (`git fetch`, `git ls-remote`) are fine. Approval is per-action, never standing. Commit locally freely; then ask.
- **C2 — adversarial self-audit before requesting a push.** Read the actual diff, verify every passing-test claim was actually run this session, check each convention against the diff, confirm design-doc acceptance criteria are genuinely met, and anticipate what a skeptical reviewer would flag. Report what the audit found — including anything it did not clear — then ask.

## Commands

```bash
uv sync                                # env + build extension (first run creates .venv)
uv run pytest                          # Python suite
uv run pytest tests/test_storage.py    # single file
uv run pytest -k round_trip            # single test by name
uv run pytest -m network               # the network tests, deselected by default
uv run ruff check . && uv run ruff format .

uv sync --reinstall-package perpcarry  # rebuild perpcarry_cpp after editing cpp/

uv run cmake -S . -B build/dev -G Ninja        # standalone C++ build
uv run cmake --build build/dev
uv run ctest --test-dir build/dev --output-on-failure
uv run ctest --test-dir build/dev -R smoke     # single C++ test by name
```

CI (`.github/workflows/ci.yml`) runs exactly these commands — `uv sync --locked`, ruff, pytest in
one job; standalone CMake + `ctest` in another — on both `ubuntu-latest` and `macos-latest`. To
reproduce a CI failure locally, run the step's command verbatim; if you change a workflow step,
run it locally first (convention C11). Note that `uv sync --locked` fails when `pyproject.toml`
changed without `uv lock`, so re-lock as part of any dependency change.

Toolchain notes worth knowing before debugging a build:

- CMake and Ninja are **dev dependencies inside `.venv`**, not system installs — hence the `uv run` prefix on every CMake command.
- scikit-build-core's editable rebuild-on-import is deliberately **off** (`editable.rebuild = false` in `pyproject.toml`). Its CMake cache points into the ephemeral build-isolation environment, which uv tears down after the sync, so imports fail with a stale ninja path. Rebuild explicitly instead.
- The standalone (non-wheel) CMake build finds pybind11 by shelling out to `python -m pybind11 --cmakedir` against the active interpreter; outside the venv it silently skips the extension module and builds only the core plus tests.
- Catch2 v3.7.1 is pulled at configure time via `FetchContent`, so the first configure needs network access.
- Python is pinned to 3.12 (`.python-version`), and `requires-python` is `>=3.12` — narrowed from `>=3.11`, which nothing had ever tested (D-008). The CMake `find_package(Python ...)` floor matches; keep the three in step.

## Working from the design doc

`docs/design-doc.md` is the source of truth for scope, architecture, and sequencing. It is explicitly a **seed document for spec-driven development**: each task in Section 5 (M0-T1, M1-T3, …) is intended to become one implementation spec/ticket.

Two rules follow from this:

1. **Check the task's dependencies before implementing.** Section 5 tables list `Depends On` for every task, and several tasks are blocked on an *open design decision* (bolded, e.g. "**OD-2 resolved**"). If you are asked to implement a task whose blocking OD is still `OPEN` in Section 6, surface that first — each OD has a documented recommendation/default that can be adopted, but the choice should be explicit, and the doc's Status line updated when it is made.
2. **Acceptance criteria are the spec.** Each task row states a concrete acceptance criterion (e.g. "no gaps in `trade_id` sequence", "withholding future data does not change historical outputs"). Implement against those, and add the test the criterion implies.

The doc has five known gaps — a missing C++-side Parquet reader, a book schema that assumes diffs the interim data source lacks, two over-tight dependency edges, a mis-sequenced fee/settlement task, and a venue-specific `trade_id` criterion. They are recorded with detail and interim paths in `docs/blockers.md`; read it before starting any milestone rather than rediscovering them.

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
