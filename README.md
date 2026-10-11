# PerpCarry

[![CI](https://github.com/nmokey/perpetuals-carry-strategy/actions/workflows/ci.yml/badge.svg)](https://github.com/nmokey/perpetuals-carry-strategy/actions/workflows/ci.yml)

Funding-rate-aware execution cost analysis for crypto perpetual futures.

**Active research: BTCUSDT and SOLUSDT**, over a common walk-forward window of
**2025-10-01 through 2026-09-30**, with prior warm-up. The primary cost model is a
regression-calibrated square-root impact law; entry will be gated by rolling Bayesian AR(1)
funding persistence. Report capacity in %ADV and USDT notional, plus gross and net-of-cost Sharpe.
See [the study plan](docs/btc-sol-study.md) and [configuration](config/btc-sol-study.toml).

The figures **0.04% ADV / $210K capacity, 0.8 net Sharpe, 2.1 gross Sharpe and 400M+ events are
claims to test, not results**. Existing `0GUSDT` data remains for engineering tests; its backfill
has stopped. First-of-month full-day books support sparse calibration, not continuous daily
execution replay. The selected study uses monthly-calibrated inferred costs with continuous funding/prices;
continuous daily books are excluded. Verified futures-bar volume supplies prior-30-day ADV.
See [current readiness and coverage](docs/current-status.md) for remaining gates.

**Research question:** for a given perpetual futures market, does the funding-rate carry edge
remain positive after realistically modeled slippage and fees — and how does that answer change
with order size and market liquidity?

The execution cost model is *calibrated* from order book data rather than assumed, and it drives
the strategy's entry threshold and position sizing. The deliverable is a capacity answer — the
size at which net-of-cost P&L crosses zero — not an equity curve.

See [`docs/design-doc.md`](docs/design-doc.md) for the full design, milestone breakdown, and open
design decisions.

## Status

**M0–M3 complete.** The ingestion layer works: partitioned Parquet storage, archive download
helpers (streamed, checksum-verified, cached), historical **trades**, **funding rate** and **L2
order book** downloaders, symbol tick/step derivation committed as a reviewed lookup table, and a
corpus-level **data validation** pass usable as a gate.

The C++ core reconstructs an L2 book from the vendor's snapshot-and-diff feed, and the replay is
checked against the vendor's *independently constructed* top-25 snapshots. The original
engineering validation compared 564,783 images across two symbols with zero mismatches;
current BTC/SOL sample validation is tracked separately in [current status](docs/current-status.md).
The criterion is exact equality with no tolerance. A failed comparison renders
as a side-by-side ladder rather than a boolean.

The pipeline is assembled end to end — Parquet → PyArrow → pybind11 → replay → lock-free SPSC queue
→ consumer. The historical 0G engineering symbol-day replayed in ~3.5s, reproducing its validated event count exactly,
and the resulting book digest is identical across runs and across an 8192× change in queue capacity.

**M4 is complete too.** The impact simulator walks the reconstructed book to price a hypothetical
order, as a single market order or worked over a window in slices, and expresses the size in units
that compare across symbols (% of average daily volume, % of visible depth).

One result from it is worth stating up front, because it shapes how the eventual capacity answer
must be read: **the vendor's reference data validates only the top 25 book levels, and orders above
roughly 0.25–0.9% of ADV walked deeper than that in the historical 0G pilot.
Those boundaries are not verified BTC/SOL capacity limits.** So the small-order end of the capacity curve rests
on independently validated book state and most of the interesting range does not. Every simulated
fill reports whether it crossed that line, so the distinction survives into the results rather than
living in a footnote.

**M5-T1–T3 are implemented; BTC/SOL fits remain gated on data validation.** Simulator bindings and a
deterministic per-fill dataset generator are present. Reconstruction passes through the SPSC
queue before isolated static/sliced cost simulation reads consumer state. Content-matched quality
and independent book-replay reports gate calibration. Square-root fitting, diagnostic alternatives
and chronological held-out residual reports are implemented. Strict per-symbol JSON export/load
preserves coefficients, provenance and coverage caveats. **M6-T1 funding analysis is complete**:
[the BTC/SOL findings](docs/analysis/M6-T1-funding-eda.md) include real ACF/PACF, stationarity
checks and strictly prior monthly diagnostics. **M6-T2 Bayesian AR(1) is implemented**;
[its predictive checks](docs/analysis/M6-T2-bayesian-funding.md) expose undercalibrated
study-year uncertainty. **M6-T3 rolling/cumulative forecasts are implemented**;
[causal checks and results](docs/analysis/M6-T3-rolling-funding.md) show improved one-step
coverage but weak weekly calibration. **M7-T1 entry/exit rules are implemented**:
configurable funding-after-cost gates, fixed holding horizons and strict evidence admission
([policy specification](docs/specs/M7/M7-T1-carry-rules.md)). **M7-T2 sizing is implemented**, separating the profit-optimal size from supported
break-even capacity ([specification](docs/specs/M7/M7-T2-position-sizing.md)).
**M7-T4 accounting is implemented**, with hand-reconciled fills, fees, funding and gross/net
equity ([specification](docs/specs/M7/M7-T4-settlement-accounting.md)).
**M7-T3 walk-forward integration is implemented**, connecting models, sizing, execution and
accounting with deterministic, causal output ([specification](docs/specs/M7/M7-T3-walk-forward.md)).
**Next: admit the inputs for M8 BTC/SOL runs**; model adequacy, actual settlement marks, historical
fee evidence and execution/collateral gates remain open. No research strategy P&L is reported yet.

Data is downloaded, not shipped: `data/` is gitignored and everything in it is re-derivable from
the M1 scripts.

Data comes from static historical archives — `data.binance.vision` for trades, funding and klines,
and the Tardis.dev free tier for L2 order book. No venue API is used: `fapi.binance.com` and Bybit
are geo-blocked from the development location. Nothing needs to run continuously.

Active BTC/SOL acquisition uses `PERPCARRY_DATA_ROOT=data/btc-sol`; completed data under the
previous root is retained for testing. Follow [the server workflow](docs/server-workflow.md).
The [code organization audit](docs/codebase-audit.md) records the cleanup and remaining
maintenance work identified before M6 implementation; its dated findings are historical.

## Layout

```
cpp/      C++ core: order book, replay, comparison + debug rendering, SPSC queue,
          threaded pipeline, pybind11 bindings; cpp/tools/ for the local dev tools
          that are allowed file I/O (the core does none)
python/   Research layer: ingestion, statistical models, strategy/backtest, reporting
          shared storage, integrity and replay adapters; tools/ owns CLI orchestration
tests/    pytest suite mirroring python/
data/     gitignored local Parquet storage
docs/     design doc, external-dependencies audit, specs, conventions, progress
```

## Setup

Requires [`uv`](https://docs.astral.sh/uv/). A C++20 compiler is needed; CMake and Ninja are
installed into the virtualenv as dev dependencies, so no system install is required.

```bash
uv sync          # creates .venv, installs deps, builds the perpcarry_cpp extension
```

## Common commands

```bash
# Python
uv run pytest                          # full Python suite (network tests deselected)
uv run pytest -m network               # tests that hit the real archive
uv run pytest tests/test_storage.py    # one file
uv run pytest -k round_trip            # one test by name
uv run ruff check .                    # lint
uv run ruff format .                   # format

# Rebuild the C++ extension after changing cpp/
uv sync --reinstall-package perpcarry

# C++ standalone build + tests
uv run cmake -S . -B build/dev -G Ninja
uv run cmake --build build/dev
uv run ctest --test-dir build/dev --output-on-failure
uv run ctest --test-dir build/dev -R smoke   # one test by name
```

The C++ test suite uses Catch2, fetched at configure time via CMake `FetchContent` (first
configure needs network access).

## CI

GitHub Actions runs both build paths on pushes to main and pull requests, across Linux and macOS:

- **`python`** — `uv sync --locked` (which compiles the extension), then ruff and pytest
- **`cpp`** — standalone CMake configure/build, then `ctest`
- **`sanitizer`** — ThreadSanitizer over the lock-free queue's stress test (Linux)

The commands are the same ones listed above, so a green CI run means the local instructions work.

The sanitizer job runs per-PR rather than nightly: it costs a few seconds, and a rigor claim CI does
not run is a claim about the past. It was verified to *fail* on a real defect — weakening the
queue's release/acquire pair to relaxed produces a reported race and a non-zero exit — because a
sanitizer that has only ever passed proves nothing. Remaining heavy checks (full backtests, a
reproducibility gate) are still planned for a nightly tier; see design doc Section 4.9.

```bash
# Reproduce the sanitizer job locally
uv run cmake -S . -B build/tsan -G Ninja -D PERPCARRY_SANITIZER=thread -D PERPCARRY_BUILD_PYTHON=OFF
uv run cmake --build build/tsan
TSAN_OPTIONS=halt_on_error=1 ./build/tsan/cpp/tests/perpcarry_tests "[spsc]"
```
