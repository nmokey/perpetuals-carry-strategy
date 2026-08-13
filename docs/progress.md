# Progress

Dated log of what actually happened. **Newest entry first.** Absolute dates only (`YYYY-MM-DD`) —
never "yesterday" or "last week". Record what was *verified*, not what was intended; anything
unverified belongs in `blockers.md` instead.

Milestone status at a glance:

| Milestone | Status |
|---|---|
| M0 — Scaffolding & environment | **Complete** (2026-08-12) |
| M1 — Data acquisition | Not started (blocked: B-001) |
| M2 — Order book reconstruction (C++) | Not started |
| M3 — Bindings & SPSC queue | Not started |
| M4 — Impact simulator (C++) | Not started |
| M5 — Impact model calibration | Not started |
| M6 — Funding persistence model | Not started |
| M7 — Strategy & backtest | Not started |
| M8 — Comparative study | Not started |
| M9 — Analysis & writeup | Not started |
| M10 — Perf benchmarking (stretch) | Not started |

---

## 2026-08-12

### Agent-orchestration docs scaffolded

Added `docs/specs/` (per-milestone subdirectories plus a spec template), `north_star.md`,
`conventions.md`, `decisions.md`, `blockers.md`, and this file. `CLAUDE.md` now points at them as
standing steering.

Seeded conventions C1–C9 from lessons already learned, including the standing rule that **no
remote action happens without explicit approval, preceded by an adversarial self-audit** (C1, C2).

### M0 complete — scaffolding & environment setup

All four M0 tasks done, each acceptance criterion verified by a command actually run:

| Task | Deliverable | Verified by |
|---|---|---|
| M0-T1 | CMake build + `uv`-managed env | `uv sync` builds `perpcarry_cpp`; `import perpcarry` succeeds |
| M0-T2 | Catch2 integrated | `uv run ctest` — 1/1 passing |
| M0-T3 | pytest + ruff | 9/9 pytest passing; `ruff check` and `ruff format --check` clean |
| M0-T4 | Parquet I/O helper | Round-trip, partition-pruning, and projection tests in `tests/test_storage.py` |

Structure created: `cpp/{include,src,bindings,tests}` with a deliberately trivial `version()` core
(stub only — see convention C5), `python/perpcarry/{ingestion,models,strategy,reporting}` package
skeleton, `python/perpcarry/storage.py` with Hive partitioning by `symbol`/`date`, root `tests/`
suite, gitignored `data/`.

Decisions taken: D-001 through D-006 (see `decisions.md`). Notably `editable.rebuild` is off after
hitting a stale-toolchain-path failure (D-003 / C8). OD-13 and OD-14 resolved, with their Status
lines updated in the design doc.

### Design doc reviewed for self-consistency

Dependency graph is acyclic and milestone stopping points are coherent. Five gaps found and
logged: B-001 (OD-2 unresolved), B-002 (no C++ Parquet reader specified), B-003 (book schema
assumes diffs the interim data source lacks), plus three watch-list items in `blockers.md`.

### Repository initialized

Git repo created on `main`, remote set to `github.com/nmokey/perpetuals-carry-strategy`. M0
scaffolding pushed as commit `4b2b00e` (approved before the C1 convention existed; all subsequent
pushes require explicit approval).
