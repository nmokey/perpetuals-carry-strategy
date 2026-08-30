# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current state

**M0 complete (T1–T6). M1 complete (T1–T5). M2 complete (T1–T3, 2026-08-29). M3 complete (T1–T3, 2026-08-29).** All three M2 specs are in `docs/specs/M2/` and all three M3 specs in `docs/specs/M3/`. The replay is validated against the vendor's own `book_snapshot_25` — 564,783 images across two symbols, zero mismatches (`docs/validation/`); read M2-T2's tolerance section and D-019 before changing the criterion, which is exact equality on every image rather than any epsilon. Working today: `storage.py` (partitioned Parquet), `ingestion/download.py` (streamed fetch, checksums, cache), `ingestion/binance_archive.py` and `ingestion/tardis_archive.py` (URL construction), `ingestion/fetch_trades.py`, `ingestion/fetch_funding.py`, `ingestion/fetch_book.py`, `ingestion/derive_symbol_meta.py` + the committed `ingestion/symbol_meta.json`, `ingestion/validate_data.py` + `ingestion/data_quality_allowlist.toml`. 292 offline + 6 network Python tests and 59 C++ tests, CI green on Linux and macOS, plus a ThreadSanitizer job over the SPSC queue.

**Vendor book data is licence-restricted and the rules are stricter than C9.** Tardis Clause 9.2(2) forbids redistributing raw rows: never commit a book fixture, never let book data reach CI, never publish anything from which a book could be reconstructed. Fitted coefficients and capacity curves are fine. Every fixture in `tests/ingestion/test_fetch_book.py` is synthetic for this reason, and a test enforces it.

Tick and step sizes are **committed data, not computed at runtime** — read them from `symbol_meta.json` via `derive_symbol_meta.load_table()`. A value that silently changed between runs would make backtests irreproducible. Currently `0GUSDT`, `BTCUSDT`, `ETHUSDT`; the table grows when OD-3 picks the study symbols.

`cpp/` holds `OrderBook`, `BookReplayer`, `compare_top_n` and the M2-T3 renderers (`format_price`, `dump_csv`, `format_ladder`, `format_diff` in `book_debug.hpp`), plus the `version()` stub; `cpp/tools/` holds the validation harness (D-018), which is deliberately outside `perpcarry_core` because it does file I/O and the core does none. The renderers take a stream or return a string and open no files — a ladder of a real symbol-day is raw per-level book data, so where it lands is the caller's choice and never a committed path. `SPSCQueue` (M3-T2) and `Pipeline` (M3-T3) are done; `Pipeline` is the **only threaded thing in the core**, and the book is still not concurrent — the `OrderBook` is owned entirely by the consumer thread and the producer never sees it. Not yet written: the impact simulator (M4), and the `models/`, `strategy/` and `reporting/` packages.

**`OrderBook` keys on `double` prices, and that is safe only because a price is never derived.** Levels are compared, never computed, so equality is exact for values parsed from the same decimal text. Any future code that does arithmetic on a *key* breaks that argument and needs integer ticks instead.

**The corpus on disk is partial and that is deliberate.** M1's *code* is complete; the bulk pull is not done. Currently `0GUSDT` June–July trades/funding plus 3 book days, and one `BTCUSDT` book day from the scale test. Before pulling the full 24 months, read the two `blockers.md` watch-list entries on archive lag and book sizing — the spec's size budget is ~2x under and the window's end date needs deciding.

**The book is validated only 25 levels deep, and M4 walks deeper than that.** This is the most important thing to know before starting M4: deleting one real update well below the top of a ~1000-level book left the replay wrong and the harness still passing, because no `book_snapshot_25` image describes that depth. The check is real — the same experiment at top-of-book produced 10 correctly-categorised mismatches — but by level count it constrains ~2.5% of the book. There is no deeper reference on the free tier. Decide how to handle it when M4-T1 is specced, not at write-up time; `blockers.md` has the options.

**Nothing needs to run continuously.** Every source is a static historical archive, so there is no recorder, no daemon, and no data that decays while a decision is pending.

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

Of the doc's five originally-known gaps, three are closed: the missing C++-side Parquet reader (D-012 — Python does the I/O, the core takes a batch), the book schema that assumed diffs the data lacks (§3.2 rewritten), and the venue-specific `trade_id` criterion. A sixth was found and closed while specifying M3: **M3-T3's criterion referenced an "M2-T2 checkpoint" that has never existed** — M2-T2 emits an aggregated JSON summary, never serialised book state. The M3-T3 spec defines it as the committed JSON counts plus a SHA-256 of M2-T3's `dump_csv`, which is exact, deterministic, and publishable where the dump itself would not be. **One remains open**, on the watch list: a mis-sequenced fee/settlement task (M7-T4 is listed after M7-T3, but T3's P&L needs it — expect a minimal settlement model inside T3). The over-tight dependency edge (M4-T2 on M3-T2) went moot on 2026-08-29 when M3-T2 completed, as M2-T1's edge on M1-T4 did before it — **no dependency edge in the doc currently blocks anything.** All are recorded with detail and interim paths in `docs/blockers.md`; read it before starting any milestone rather than rediscovering them.

**OD-2, OD-5 and now OD-6 are resolved** — the last on 2026-08-29 as option (b), single-threaded book core plus an SPSC queue (D-020). No open design decision gates M3. Two things D-020 adds that the design doc's §6 does not: option (c) cannot be benchmarked honestly, because a backtest replays one totally ordered stream and has no concurrent writers for per-level locking to protect against; and the queue may change *when* an item is consumed but never *which* or *in what order*, so no simulation behaviour may depend on queue occupancy or producer timing — otherwise determinism goes with it. The next OD that blocks work is **OD-7** (impact model functional form) at M5-T2. Everything M4 and later still has its OD open, so check `decisions.md` before starting one rather than at the point it bites.

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

- `cpp/{include/perpcarry,src,bindings,tests,tools}` — C++20, CMake, pybind11, Catch2. `tools/` is where file I/O is allowed to live; `perpcarry_core` does none (D-012/D-018), and building the tests without the tools is a hard error rather than a quietly smaller suite. **ThreadSanitizer is wired up** (M3-T2, B-008): `-D PERPCARRY_SANITIZER=thread` plus the `sanitizer` CI job over the `[spsc]` tag, with `TSAN_OPTIONS=halt_on_error=1`. It was verified to fail on a real defect, not merely to pass.
- `python/perpcarry/{ingestion,models,strategy,reporting}` — the wheel packages this directory; `tests/` at the repo root is the pytest suite mirroring it.
- `data/` is gitignored; everything under it is re-derivable from the M1 ingestion scripts. `PERPCARRY_DATA_ROOT` overrides the location.
- Bayesian inference on the critical path should be hand-rolled closed-form conjugate updating (Normal-Inverse-Gamma); PyMC/MCMC is an optional M9 addendum only (OD-8), which is why PyMC is not a dependency.

Two import names, easy to confuse: `perpcarry` is the pure-Python package under `python/`; `perpcarry_cpp` is the compiled extension, installed as a **top-level** module (not nested inside `perpcarry`) to match the M3-T1 acceptance criterion.

**`perpcarry_cpp`'s surface is pinned by a test and is meant to stay small** (M3-T1): `Side`, `BookUpdate`, `ReplayStats`, `OrderBook`, `BookReplayer`, `BookReplayError`, `Pipeline`, `PipelineResult`, `dump_csv`, `version`. Adding a symbol fails `test_public_surface_is_exactly_what_the_spec_names` on purpose. Two rules the bindings encode rather than merely document: **levels cross as copied `(price, quantity)` tuples**, never as a view over `OrderBook`'s span — that span is invalidated by the next `apply()`, and a stale view surfaces as a plausible wrong fill price rather than a crash; and **`BookReplayer` has no single-row entry point**, because the batch is the unit of interop (Risk R4) and a per-row `apply` is the tempting mistake. Both are guarded by tests, one of which segfaults when the keep-alive policy is wrong.

## Milestone sequencing

M0 → M1 (data) → M2 (C++ book) → M3 (bindings + SPSC) → M4 (impact simulator) → M5 (calibration) → M6 (funding model) → M7 (strategy + backtest) → M8 (comparative study) → M9 (writeup) → M10 (perf, stretch).

The ordering is intentional (Risk R3): M0–M4 alone is a complete systems artifact, M7 a complete research pipeline, M9 a polished writeup. Prefer finishing a milestone to starting the next one.
