# PerpCarry

[![CI](https://github.com/nmokey/perpetuals-carry-strategy/actions/workflows/ci.yml/badge.svg)](https://github.com/nmokey/perpetuals-carry-strategy/actions/workflows/ci.yml)

Funding-rate-aware execution cost analysis for crypto perpetual futures.

**Research question:** for a given perpetual futures market, does the funding-rate carry edge
remain positive after realistically modeled slippage and fees — and how does that answer change
with order size and market liquidity?

The execution cost model is *calibrated* from order book data rather than assumed, and it drives
the strategy's entry threshold and position sizing. The deliverable is a capacity answer — the
size at which net-of-cost P&L crosses zero — not an equity curve.

See [`docs/design-doc.md`](docs/design-doc.md) for the full design, milestone breakdown, and open
design decisions.

## Layout

```
cpp/      C++ core: order book reconstruction, impact simulation, SPSC queue, pybind11 bindings
python/   Research layer: ingestion, statistical models, strategy/backtest, reporting
tests/    pytest suite mirroring python/
data/     gitignored local Parquet storage
docs/     design doc
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
uv run pytest                          # full Python suite
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

GitHub Actions runs both build paths on every push and pull request, across Linux and macOS:

- **`python`** — `uv sync --locked` (which compiles the extension), then ruff and pytest
- **`cpp`** — standalone CMake configure/build, then `ctest`

The commands are the same ones listed above, so a green CI run means the local instructions work.
Heavier checks (ThreadSanitizer, full backtests, a reproducibility gate) are planned for a nightly
tier — see design doc Section 4.9.
