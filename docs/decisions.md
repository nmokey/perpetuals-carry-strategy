# Decisions

Two kinds of decision live here:

- **OD-N** — the open design decisions from `design-doc.md` Section 6. This file tracks their
  resolution status; the design doc holds the full options analysis.
- **D-NNN** — implementation decisions taken during build that the design doc did not specify.

When an OD is resolved, update both the table below *and* the Status line in the design doc.

---

## OD status

| ID | Topic | Status | Blocks |
|---|---|---|---|
| OD-1 | Exchange/venue selection | OPEN (default: Binance Futures) | M1 |
| OD-2 | Historical L2 book acquisition | **OPEN — highest risk** | M1-T3 → everything downstream |
| OD-3 | Symbol selection | OPEN (deliberately deferred to M8) | M8-T2 |
| OD-4 | Spot leg treatment | OPEN, leaning frictionless spot | M7, M8 |
| OD-5 | Book reconstruction fidelity | Leaning resolved: L2 | M2-T1 |
| OD-6 | Concurrency model | OPEN, strongly leaning (b) single-threaded core + SPSC queue | M3-T2 |
| OD-7 | Impact model functional form | OPEN (recommendation: fit both, compare) | M5-T2 |
| OD-8 | Bayesian inference method | OPEN, leaning closed-form conjugate | M6-T2 |
| OD-9 | Entry/exit threshold policy | OPEN, leaning credible-interval | M7-T1 |
| OD-10 | Position sizing / capacity model | OPEN, leaning capacity-curve | M7-T2, M8-T3 |
| OD-11 | Fee & funding settlement assumptions | OPEN — needs venue research | M7-T4 |
| OD-12 | Backtest validation methodology | OPEN, leaning walk-forward | M7-T3 |
| OD-13 | Build tooling | **RESOLVED 2026-08-12** — see D-001 | M0 |
| OD-14 | Data storage format | **RESOLVED 2026-08-12** — Parquet/PyArrow, DuckDB optional | M0-T4, M1 |

---

## D-001 — scikit-build-core as the build backend (2026-08-12)

**Context.** OD-13 specifies CMake + pybind11 but not how the wheel gets built.

**Decision.** `scikit-build-core` drives CMake for the wheel; a parallel standalone CMake path
(`uv run cmake -S . -B build/dev`) builds the core plus the Catch2 tests for C++-only work.

**Consequence.** Two build entry points that must not drift. `PERPCARRY_BUILD_TESTS` is forced off
under `SKBUILD` so wheel builds don't pull Catch2 over the network.

---

## D-002 — CMake and Ninja as venv dev dependencies (2026-08-12)

**Context.** No system CMake or Ninja on the development machine.

**Decision.** Install both from PyPI into `.venv` as dev dependencies. See convention C7.

**Alternative rejected.** Requiring a Homebrew CMake — adds an undocumented prerequisite for
anyone cloning the repo.

---

## D-003 — `editable.rebuild` disabled (2026-08-12)

**Context.** scikit-build-core can rebuild the extension automatically on import.

**Decision.** Disabled. Rebuild explicitly with `uv sync --reinstall-package perpcarry`.

**Why.** The generated CMake cache references uv's ephemeral build-isolation environment, which
is torn down after the sync; the next import then fails on a stale `ninja` path. Observed
directly. See convention C8.

---

## D-004 — `perpcarry_cpp` installs as a top-level module (2026-08-12)

**Context.** The extension could be nested inside the `perpcarry` package instead.

**Decision.** Top-level, matching the M3-T1 acceptance criterion's wording ("`perpcarry_cpp`
importable Python extension").

**Consequence.** Two import names to keep straight: `perpcarry` (pure Python) and `perpcarry_cpp`
(compiled).

---

## D-005 — Python pinned to 3.12 (2026-08-12)

**Context.** The design doc says 3.11+; the machine's default interpreter is 3.14.

**Decision.** `.python-version` pins 3.12 for wheel coverage across the scientific stack;
`requires-python` stays `>=3.11`.

**Revisit when.** The scientific stack has settled 3.13/3.14 wheels and there is a reason to move.

---

## D-006 — PyMC deliberately not a dependency (2026-08-12)

**Context.** OD-8 lists MCMC as an option for the Bayesian funding model.

**Decision.** Not installed. The critical path uses hand-rolled closed-form conjugate updating;
PyMC would only appear if the optional M9 MCMC addendum is actually pursued.

**Why.** Keeps the rolling backtest cheap enough to re-run at every walk-forward step, and keeps a
heavy dependency out of the environment until it is earned.
