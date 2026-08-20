# Design Document: PerpCarry
## Funding-Rate-Aware Execution Cost Analysis for Crypto Perpetual Futures

**Status:** Draft v1
**Author:** Ryan Zheng
**Purpose:** Seed document for spec-driven development. Each task in Section 5 is intended to become one implementation spec/ticket. Open decisions in Section 6 should be resolved (or explicitly deferred with a documented default) before specs are written for the milestones they affect.

---

## Table of Contents

1. [Overview](#1-overview)
2. [System Architecture](#2-system-architecture)
3. [Data Model & Sources](#3-data-model--sources)
4. [Component Specifications](#4-component-specifications)
5. [Milestones & Task Breakdown](#5-milestones--task-breakdown)
6. [Open Design Decisions](#6-open-design-decisions)
7. [Success Metrics](#7-success-metrics)
8. [Risks & Mitigations](#8-risks--mitigations)
9. [Repository Structure](#9-repository-structure)
10. [Tech Stack Summary](#10-tech-stack-summary)
11. [Glossary](#11-glossary)

---

## 1. Overview

### 1.1 Problem Statement

Perpetual futures track their underlying spot asset through periodic **funding payments** exchanged between long and short holders. When funding is persistently elevated, a textbook cash-and-carry trade exists (short perp / long spot, collect funding). This trade is well known. What's underexplored — and what this project investigates — is whether the funding edge actually **survives realistic execution costs**, and if so, at what trade size it stops being worth it.

### 1.2 Core Research Question

> For a given perpetual futures market, does the funding-rate carry edge remain positive after realistically modeled slippage and fees — and how does that answer change with order size and market liquidity?

### 1.3 Why This Framing

Most student quant projects either (a) build a generic backtester with an assumed flat transaction cost, or (b) build a market-impact model in isolation with no strategy attached. This project ties the two together: the **execution cost model is calibrated from real order book data**, not assumed, and it directly determines the strategy's entry threshold and position sizing. The deliverable isn't "a profitable strategy" — it's a rigorous, honest answer to a capacity question, which is arguably more valuable as a research artifact than a backtest that just shows a nice equity curve.

### 1.4 Non-Goals

- **Not** a live trading system — no order routing, no exchange connectivity beyond historical/read-only data pulls.
- **Not** a multi-asset portfolio optimizer — scope is intentionally narrow (one strategy, 1-2 symbols) to stay deep rather than broad.
- **Not** a production-grade feed handler — the systems work (Section 2, Section 6 OD-6) should be rigorous and honestly motivated, but this is a research-scale artifact, not a literal HFT stack with hardware timestamping.
- **Not** attempting to fully simulate the spot leg of the carry trade (see OD-4) — the perp execution leg is the novel part; the spot/index leg is treated as a simplifying assumption, documented as such.

---

## 2. System Architecture

```
┌───────────────────────┐
│   Exchange Data         │
│ (trades, depth,         │
│  funding rates)          │
└───────────┬─────────────┘
            │
            v
┌───────────────────────┐
│   Ingestion Layer        │  (Python)
│   fetch_*.py scripts     │
└───────────┬─────────────┘
            │ Parquet
            v
┌───────────────────────┐
│   Storage Layer           │  (Parquet, local filesystem)
└───────────┬─────────────┘
            │ PyArrow read (Python owns all Parquet I/O — D-012)
            v
┌───────────────────────┐
│   Replay Driver          │  (Python) — reads rows, hands over a batch
└───────────┬─────────────┘
            │ pybind11 — once per batch, never per tick (Risk R4)
            v
┌─────────────────────────────────────────────────┐
│              C++ Core (perpcarry_cpp)              │
│  ┌────────────────┐   SPSC    ┌─────────────────┐ │
│  │ Ingestion        │ ────────>│ Simulation        │ │
│  │ Thread            │  queue   │ Thread             │ │
│  │ (BookReplayer)    │          │ (OrderBook,        │ │
│  │                   │          │  ImpactSimulator)  │ │
│  └────────────────┘           └────────┬─────────┘ │
└─────────────────────────────────────────┼───────────┘
                                            │ pybind11
                                            v
┌─────────────────────────────────────────────────┐
│              Python Research Layer                 │
│  Impact Model Calibration │ Funding Bayesian Model │
│  Strategy Logic            │ Backtest Engine         │
└──────────────────────┬────────────────────────────┘
                        │
                        v
              ┌──────────────────────┐
              │ Reporting / Analysis   │
              └──────────────────────┘
```

**Design rationale:** correctness-critical, deterministic logic (book reconstruction) lives in a single-threaded C++ core for testability. Concurrency is introduced only at the point where it's realistically motivated — decoupling data ingestion from simulation via a lock-free queue, mirroring how real feed-handler → strategy-engine boundaries work (see OD-6). The Python layer owns everything statistical: regression, Bayesian inference, strategy decisions, and reporting.

The C++ core does no file I/O in either direction (D-012). Python reads the Parquet with PyArrow and passes a batch of rows across the pybind11 boundary; the core takes an in-memory batch, not a path. This keeps the boundary at the pipeline level per Risk R4 and keeps Arrow C++ out of the build. The tradeoff is that replay input is materialised before it crosses, so peak memory scales with batch size — revisit only if M10 profiling shows the boundary dominating.

---

## 3. Data Model & Sources

### 3.1 Trades

| Field | Type | Notes |
|---|---|---|
| `timestamp` | int64 (ms epoch) | Exchange trade time |
| `trade_id` | int64 | Used for gap detection |
| `symbol` | string | e.g. `BTCUSDT` |
| `price` | float64 | |
| `quantity` | float64 | Base asset units |
| `side` | enum (`buy`/`sell`) | Aggressor side |

### 3.2 Order Book (L2 snapshots + diffs)

Source: Tardis.dev `incremental_book_L2` for `binance-futures` (see OD-2). Its native columns are
`exchange, symbol, timestamp, local_timestamp, is_snapshot, side, price, amount`, which map onto
this schema directly — including the `amount = 0` convention for level removal.

| Field | Type | Notes |
|---|---|---|
| `timestamp` | int64 (µs epoch in source; normalised to ms on ingest) | Exchange timestamp |
| `local_timestamp` | int64 | Capture timestamp; the gap to `timestamp` is the vendor's observed latency |
| `symbol` | string | |
| `is_snapshot` | bool | Marks the start-of-file book image; replay resets state here |
| `side` | enum (`bid`/`ask`) | |
| `price` | float64 | |
| `quantity` | float64 | `0` = price level removed |

**No `update_id`.** The vendor feed carries no sequence number, so dropped-diff detection cannot be
sequence-based. Continuity is instead established by (a) each file opening with an `is_snapshot`
block, and (b) validating replayed state against an independent `book_snapshot_25` for the same
day (M2-T2). This is weaker than sequence checking and must be stated as such.

### 3.3 Funding Rate

Source: `data.binance.vision` monthly `fundingRate`, whose native columns are `calc_time,
funding_interval_hours, last_funding_rate`.

| Field | Type | Notes |
|---|---|---|
| `symbol` | string | Not a column in the source; injected from the archive path |
| `funding_time` | int64 (ms epoch) | Source column `calc_time`. Jitters by ~1 ms between settlements — see M1-T2 |
| `funding_rate` | float64 | Source column `last_funding_rate`; e.g. `0.0001` = 1 bp |
| `funding_interval_hours` | int32 | **Not a constant, and not even a per-symbol constant.** Measured: majors 8h; `1000BONKUSDT` 4h; `0GUSDT` ran 4h at listing, 1h from 2025-09-22, 4h again by 2026-06. Required to annualise — read it per row, never per symbol |

**`mark_price` is deliberately absent.** It was specified in an earlier draft, but the venue does
not publish it alongside funding history, and it is unused before M7-T4. If settlement price is
needed there, source it from `markPriceKlines` at that point rather than carrying a mostly-unused
column through the pipeline.

### 3.4 Storage

All datasets stored as partitioned Parquet (`symbol=.../date=...`), read via PyArrow/Polars. DuckDB used as an optional ad hoc SQL layer over the Parquet files for exploratory analysis — no persistent database server required. (See OD-14.)

**Footprint.** Trades and funding are small. Order book data is not: one day of `BTCUSDT`
`incremental_book_L2` is ~449 MB compressed. At the free tier's one-day-per-month cadence that is
~5.4 GB/year compressed and several times that decompressed, so the number of months pulled is a
deliberate choice (see OD-2), not an afterthought.

---

## 4. Component Specifications

### 4.1 Data Ingestion Pipeline (Python)
Pulls historical trades, funding rates, and order book data, and outputs validated, gap-checked
Parquet files. Two sources, both static file downloads rather than live API calls:

| Data | Source |
|---|---|
| Trades, funding rates, klines | `data.binance.vision` (S3 archive) |
| L2 order book | Tardis.dev free tier, `binance-futures` (see OD-2) |

**The venue's live REST/WebSocket API is not used, because it is not reachable.** `fapi.binance.com`
returns `"Service unavailable from a restricted location"` from the development location, as does
Bybit; the S3 archive and the vendor are unaffected. This rules out live capture and any REST-based
validation, and is the reason M2-T2/M2-T3 validate against vendor snapshots rather than an
exchange endpoint. Full evidence in `external-dependencies-audit.md`.

A consequence worth stating plainly: this project cannot be extended to live/paper trading from
this location without changing venue. That is consistent with the §1.4 non-goals, but it is now a
hard constraint rather than a choice.

### 4.2 Order Book Reconstruction Engine (C++)
Maintains L2 book state from a snapshot + sequential diffs. Deterministic, single-threaded, unit-testable against known checkpoints.

### 4.3 Execution / Market Impact Simulator (C++)
Given a hypothetical order (side, size, timing), walks the reconstructed book to compute realized fill price and slippage. Supports both a static single-shot book walk and a time-sliced TWAP/VWAP-style simulation against an evolving book.

### 4.4 Python Bindings (pybind11)
Exposes `OrderBook`, `BookReplayer`, and the impact simulator to Python. Boundary is the SPSC-queue-decoupled pipeline output — not a per-tick call across the C++/Python boundary, to keep interop overhead out of the "low-latency" story (see OD-6, Risk R4 in Section 8).

### 4.5 Impact Model Calibration (Python, regression)
Fits a market impact model (linear and/or square-root functional form, see OD-7) against simulated slippage data across a range of order sizes, using out-of-sample validation rather than in-sample fit alone.

### 4.6 Funding Persistence Model (Bayesian, Python)
Models funding rate as an AR(1) process with Bayesian parameter estimation, updated in a strictly rolling/online fashion (no look-ahead — see OD-12). Produces a posterior predictive distribution over cumulative future funding, not just a point estimate.

### 4.7 Strategy & Backtest Engine (Python)
Combines the impact model (expected cost) and funding model (expected + uncertain edge) into entry/exit/sizing decisions. Runs a walk-forward backtest, producing P&L, a capacity curve, and a naive-baseline comparison.

### 4.8 Reporting & Analysis
Capacity curves, BTC-vs-altcoin comparison, sensitivity sweeps, written summary.

### 4.9 Continuous Integration
GitHub Actions runs, on every push and pull request, the lint/pytest suite and the standalone
CMake + `ctest` build, across Linux and macOS. Two build paths exist (the scikit-build-core wheel
build and the standalone CMake build, see `decisions.md` D-001) and CI is what keeps them from
drifting apart; the Linux leg is also the only thing compiling this project with anything other
than AppleClang.

CI is tiered as the project grows, because the expensive checks cannot live in the per-PR path:

| Tier | Contents | Trigger |
|---|---|---|
| Per-PR | ruff, pytest, `ctest`, both OSes | push / PR |
| Nightly | ThreadSanitizer queue stress (M3-T2), full backtests (M8), reproducibility gate | schedule |

The **reproducibility gate** is the important one: a scheduled end-to-end re-run that fails if
headline results move without a corresponding commit. That is the automated form of this
project's central rigor claim, and the same reasoning applies to the look-ahead poisoning test
(M7-T3) and the fixed-seed determinism checks — invariants that are asserted once and never
re-checked decay silently.

Network-dependent tests (the M1 ingestion pulls) are marked and deselected by default. CI must
never depend on a live exchange endpoint: it makes red builds ambiguous, and under OD-2 option (b)
it risks caching licensed vendor data in CI artifacts.

---

## 5. Milestones & Task Breakdown

Each milestone can, in principle, stop and produce a coherent deliverable on its own (see Section 8, Risk R3 — scope control).

### M0 — Project Scaffolding & Environment Setup

| ID | Task | Deliverable | Acceptance Criteria | Depends On |
|---|---|---|---|---|
| M0-T1 | Repo & build system setup | CMake-based C++ build; `uv`-managed Python env | `cmake --build` succeeds; `uv run python -c "import perpcarry"` succeeds against a stub module | — |
| M0-T2 | C++ test framework setup | Catch2 (or GoogleTest) integrated | One trivial passing C++ unit test runs via `ctest` | M0-T1 |
| M0-T3 | Python test/lint setup | pytest + ruff configured | One trivial passing pytest test; `ruff check` passes on empty scaffold | M0-T1 |
| M0-T4 | Parquet I/O utility | Read/write helper for tabular data | Round-trip test: write a sample DataFrame, read it back, assert *exact* equality — values bit-for-bit and dtypes unchanged, with no tolerance and no coercion; any deviation (partitioned column order, row order) asserted explicitly rather than smoothed over | M0-T1 |
| M0-T5 | Continuous integration | GitHub Actions workflow running both build paths on Linux and macOS | Lint, pytest, and `ctest` all run per push/PR on both platforms; a deliberately broken commit fails the run | M0-T2, M0-T3 |
| M0-T6 | Ingestion dependencies | HTTP client + archive extraction helpers in the environment | A checksum-verified archive can be downloaded, extracted, and read into a DataFrame by a test; no M1 script needs to add a dependency | M0-T4 |

### M1 — Data Acquisition Pipeline

| ID | Task | Deliverable | Acceptance Criteria | Depends On |
|---|---|---|---|---|
| M1-T1 | Historical trades downloader | `fetch_trades.py`, using the archive's **`trades`** dataset (not `aggTrades`) | Daily summed quantity equals the same day's `klines` volume **exactly** (measured: zero difference across three symbols, incl. 1.9M fractional-qty trades); `trade_id` free of *runs* of absent IDs beyond the venue's observed isolated-skip noise, within and across days (contiguity itself does not hold — see D-015) | M0-T4, M0-T6 |
| M1-T2 | Historical funding rate downloader | `fetch_funding.py` | Settlement count equals `24 / funding_interval_hours × days`; consecutive settlements are one interval apart within a ±5s tolerance (source timestamps jitter ~1 ms) | M0-T4, M0-T6 |
| M1-T3 | Order book historical data acquisition | `fetch_book.py`, pulling Tardis free-tier `incremental_book_L2` | Book state reconstructable at any timestamp within a downloaded day; replayed top-25 levels match the same day's `book_snapshot_25` | M0-T4, M0-T6 |
| M1-T4 | Data validation/QA pass | `validate_data.py` | Zero *unexplained* gaps, duplicate timestamps, or non-monotonic sequences; every acknowledged gap carries a documented reason in a committed allowlist | M1-T1, M1-T2, M1-T3, M1-T5 |
| M1-T5 | Symbol metadata derivation | `derive_symbol_meta.py` + committed lookup table | Tick and step size recovered by GCD over trades sampled from disjoint windows spanning the study period; recovered values stable across those windows for the same symbol, and an estimate with too few distinct observations pooled across them is reported low-confidence rather than committed | M1-T1 |

Note the dependency order within M1: T5 precedes T4 despite the numbering, since the QA pass
validates the derived metadata alongside everything else. T5 is numbered last because it was
identified last — during the external-dependencies audit, not in the original design.

### M2 — Order Book Reconstruction Engine (C++)

| ID | Task | Deliverable | Acceptance Criteria | Depends On |
|---|---|---|---|---|
| M2-T1 | Core price-level data structure | `OrderBook` class: add/modify/delete at price level, best bid/ask query | Unit tests cover top-of-book and deep-level updates; matches independently-reconstructed reference book on a sample window | M1-T4, **OD-5 resolved** |
| M2-T2 | Snapshot + diff replay logic | `BookReplayer` | Replayed state matches the vendor's independently-constructed `book_snapshot_25` for the same day, top 25 levels, within documented tolerance | M2-T1 |
| M2-T3 | Book state debug serialization | Dump-to-CSV/human-readable function | Automated diff against `book_snapshot_25` at 3+ sample timestamps, with human-readable output for inspection when it fails | M2-T2 |

### M3 — Python Bindings & Ingestion Pipeline Concurrency

| ID | Task | Deliverable | Acceptance Criteria | Depends On |
|---|---|---|---|---|
| M3-T1 | pybind11 bindings | `perpcarry_cpp` importable Python extension | Book state queried from Python matches C++ fixture tests | M2-T2 |
| M3-T2 | Lock-free SPSC queue | `SPSCQueue<T>` decoupling ingestion thread from simulation thread | Stress test: N million events, zero loss, no data race under ThreadSanitizer; throughput benchmark recorded | M2-T2, **OD-6 resolved** |
| M3-T3 | End-to-end pipeline smoke test | One-day replay through full pipeline | Completes without error; final state matches M2-T2 checkpoint | M3-T1, M3-T2 |

### M4 — Execution / Market Impact Simulator (C++)

| ID | Task | Deliverable | Acceptance Criteria | Depends On |
|---|---|---|---|---|
| M4-T1 | Static book-walk simulator | `simulate_market_order(book, side, size)` | Unit tests against hand-computed book-walk examples | M2-T2 |
| M4-T2 | Time-sliced TWAP/VWAP simulator | `simulate_sliced_execution(...)` against evolving book | On synthetic test book: slippage increases monotonically with size (fixed window), decreases with longer duration (fixed size) | M4-T1, M3-T2 |
| M4-T3 | Order size normalization | Express size as % of ADV or % of top-N depth | Unit tested against known ADV figures for test symbol/date | M4-T2 |

### M5 — Impact Model Calibration (Python)

| ID | Task | Deliverable | Acceptance Criteria | Depends On |
|---|---|---|---|---|
| M5-T1 | Calibration dataset generation | Reproducible script sweeping (size, time, symbol) through M4 simulator | Deterministic given fixed seed; output Parquet dataset | M4-T3 |
| M5-T2 | Fit impact model(s) | Fitted coefficients + diagnostics (residuals, R², out-of-sample fit) | Documented comparison of functional forms (OD-7); out-of-sample R² reported | M5-T1, **OD-7 resolved** |
| M5-T3 | Model serialization | Saved params (JSON) + loader | Loader round-trips saved params without loss | M5-T2 |

### M6 — Funding Rate Persistence Model (Bayesian)

| ID | Task | Deliverable | Acceptance Criteria | Depends On |
|---|---|---|---|---|
| M6-T1 | Exploratory analysis | ACF/PACF plots, stationarity checks | Documented notebook/report | M1-T4 |
| M6-T2 | Bayesian AR(1) implementation | `funding_model.py` | Recovers known true parameters within credible interval on synthetic AR(1) data; posterior predictive checks look reasonable on real data | M6-T1, **OD-8 resolved** |
| M6-T3 | Rolling/online update logic | `RollingFundingModel.predict_cumulative_funding(horizon)` | Unit test confirms no look-ahead: withholding/shuffling future data does not change historical outputs | M6-T2 |

### M7 — Strategy Logic & Backtest Engine

| ID | Task | Deliverable | Acceptance Criteria | Depends On |
|---|---|---|---|---|
| M7-T1 | Entry/exit rule logic | `CarryStrategy` class | Unit tests for each decision branch on synthetic inputs | M5-T3, M6-T3, **OD-9 resolved** |
| M7-T2 | Position sizing / capacity logic | Sizing function bounded by modeled marginal impact cost | Matches expected behavior on hand-constructed test cases | M7-T1, **OD-10 resolved** |
| M7-T3 | Walk-forward backtest loop | `run_backtest.py` | Reproducible given fixed seed; "future data poisoning" test confirms no leakage | M7-T2, **OD-12 resolved** |
| M7-T4 | Fee & funding settlement accounting | P&L module incorporating real fee schedule + funding timing | P&L reconciles against a hand-computed example trade | M7-T3, **OD-11 resolved** |

### M8 — Full Backtest: BTC vs. Altcoin Comparative Study

| ID | Task | Deliverable | Acceptance Criteria | Depends On |
|---|---|---|---|---|
| M8-T1 | Full backtest — liquid symbol | P&L series, Sharpe, max drawdown, capacity curve | Runs end-to-end without manual intervention | M7-T4 |
| M8-T2 | Full backtest — illiquid symbol | Same outputs, second symbol | Same | M7-T4, **OD-3 resolved** |
| M8-T3 | Sensitivity sweep | Grid over order size / entry threshold / holding period | Results stored as Parquet, reproducible | M8-T1, M8-T2 |
| M8-T4 | Naive-baseline comparison | Side-by-side: impact-aware vs. flat-cost-assumption strategy | Quantifies overstatement of returns from ignoring impact modeling | M8-T1, M8-T2 |

### M9 — Analysis, Reporting & Writeup

| ID | Task | Deliverable | Acceptance Criteria | Depends On |
|---|---|---|---|---|
| M9-T1 | Capacity curve visualizations | Plots, per symbol | Reviewed for clarity/correctness | M8-T3 |
| M9-T2 | Written methodology + results summary | Markdown/PDF report | Answers the core research question (Section 1.2) explicitly, with caveats | M8-T4, M9-T1 |
| M9-T3 | Resume-ready summary bullets | 2-3 bullet variants (QT-framed, QR-framed) | Reviewed against original resume-feedback gaps | M9-T2 |
| M9-T4 | README + architecture diagram | Repo-level documentation | New reader can build and run the pipeline from README alone | M9-T2 |

### M10 — Performance Benchmarking & Optimization (Stretch)

| ID | Task | Deliverable | Acceptance Criteria | Depends On |
|---|---|---|---|---|
| M10-T1 | Throughput benchmarking | Order book updates/sec, simulator throughput | Numbers documented with methodology (hardware, dataset size) | M4-T2, M3-T2 |
| M10-T2 | Profiling & hot-path optimization | Optimized data structure (e.g. flat array vs. `std::map`) if justified | Before/after benchmark comparison | M10-T1 |
| M10-T3 | Document performance results | Quantified improvement (e.g. "Nx throughput") | Included in M9-T3 resume bullets | M10-T2 |

---

## 6. Open Design Decisions

Each decision below should be resolved (or explicitly deferred with a stated default) before specs are written for the milestone(s) it blocks.

**OD-1 — Exchange/venue selection**
*Affects: M1, M1-T3.*
Options: Binance Futures (deepest free historical data via `data.binance.vision`, 8h funding for most symbols), Bybit, OKX.
Recommendation: Binance Futures, for data availability.
Status: **RESOLVED 2026-08-12 — Binance USD-M futures**, for the whole project. The reasoning is
stronger than originally stated but for a different reason: the S3 archive carries years of
trades and funding and is freely reachable, while the *live* API is geo-blocked from the
development location. Binance is therefore the best available source for history and unusable for
live capture — which is fine, since nothing in scope needs live data. Bybit is also geo-blocked;
OKX is reachable but its funding history is only ~3 months deep, which would gut M6. See
`external-dependencies-audit.md`.

**OD-2 — Historical L2 order book data acquisition** *(highest-risk decision — resolve first)*
*Affects: M1-T3 and everything downstream.*
Context: Trades and funding rates are commonly archived for free; full L2 depth history generally is not. This is a real feasibility constraint, not a minor detail.
Options as originally framed:
- (a) Record live via websocket depth-diff stream going forward for several weeks — free, but delays timeline and limits the analysis window to what's recorded.
- (b) Purchase a limited historical range from a tick-data vendor (e.g. Tardis.dev) — fast, higher fidelity, has a cost.
- (c) Approximate using top-of-book / partial-depth snapshots (free, immediately available) — understates slippage for larger synthetic orders since deep-book behavior isn't captured.

**All three were checked against reality on 2026-08-12, and two do not survive:**
- (a) is unavailable on Binance from the development location (geo-blocked). It would require
  switching venue to OKX, whose ~3-month funding history would gut M6.
- (c) **does not exist as described.** The free `bookDepth` dataset is not an order book — it is
  cumulative depth at 12 fixed percentage bands from mid, ~30s irregular sampling, no sequence
  numbers, no per-level prices. `bookTicker` (L1) was discontinued after 2024-03-30. Neither can
  drive a book walk, so "start with (c) to unblock M2" was never an available path.

Status: **RESOLVED 2026-08-12 — option (d), the vendor's free tier.** Tardis.dev serves
`incremental_book_L2` for `binance-futures` with no API key, for **the first day of every month**,
back to at least 2020 (verified: 1st → HTTP 200, all other days → 401). Its format matches §3.2
including the `amount = 0` removal convention, and it is the same venue as the trades and funding
archive, so single-venue integrity holds.

Sparse coverage is acceptable because the architecture already decouples it: M5 calibrates an
impact *model* from book data and M7's backtest consumes the fitted model, never the raw book.
Continuous coverage was never required — only enough book days to fit and out-of-sample validate.

Two sub-decisions remain open, and both are cost/scope rather than feasibility:
- **How many months to pull.** ~449 MB compressed per BTCUSDT day. Start with 12–24 months.
- **Licensing.** The vendor's terms for free samples have **not** been reviewed. Do this before
  relying on the data; it must never be committed or enter CI caches (C9).

Trade-off to state in the writeup: the book data is 12 days/year rather than continuous, and
carries no sequence numbers, so dropped-update detection is snapshot-comparison-based rather than
sequence-based.

**OD-3 — Symbol selection**
*Affects: M8-T2.*
Context: Need one liquid control symbol and one genuinely thinner symbol with usable public history. Liquidity rankings drift, so pre-committing to a specific altcoin now risks it becoming irrelevant by build time.
Recommendation: BTC as control; select the altcoin based on live ADV/liquidity data at the time M8 begins, not now.
Status: OPEN.

**OD-4 — Spot leg treatment**
*Affects: M7, M8.*
Context: A true cash-and-carry trade has a spot (or second futures) leg. Fully modeling its execution cost doubles scope.
Recommendation: Treat spot/index as a frictionless reference price for v1; the perp leg's execution cost is the novel contribution. State this simplification explicitly.
Status: OPEN, leaning frictionless-spot.

**OD-5 — Order book reconstruction fidelity**
*Affects: M2-T1.*
Options: L2 (price-level aggregated) vs. L3 (order-level).
Recommendation: L2 — matches realistically available data and is standard practice for signal research even at many trading firms.
Status: Leaning resolved (L2); confirm before M2-T1.

**OD-6 — Concurrency model**
*Affects: M3-T2.*
Context: A backtest replay doesn't inherently require multithreading; forcing concurrency into the book itself purely to "look impressive" would be artificial and hard to defend under questioning.
Options:
- (a) Fully single-threaded — simpler, but drops a resume-differentiating systems element.
- (b) Single-threaded deterministic book core + lock-free SPSC queue decoupling ingestion/replay from simulation — mirrors a real feed-handler → strategy-engine boundary, genuinely motivated.
- (c) Fully concurrent book with per-price-level locking/lock-free updates — realistic for live systems, but there are no real concurrent writers in a backtest, so the complexity isn't earned.
Recommendation: (b). It's honestly motivated and gives a defensible artifact rather than a contrived one — this is the version worth being able to explain clearly in an interview.
Status: OPEN, strongly leaning (b).

**OD-7 — Impact model functional form**
*Affects: M5-T2.*
Options: linear (Almgren-Chriss-style temporary/permanent split), square-root law, or fit both and compare.
Recommendation: Fit both — the comparison itself (e.g., "square-root fit the altcoin better, linear fit BTC better") is a legitimate finding worth reporting.
Status: OPEN.

**OD-8 — Bayesian inference method**
*Affects: M6-T2.*
Options: closed-form conjugate (Normal-Inverse-Gamma for AR(1)) — fast, transparent, easy to run online; MCMC (PyMC/Stan) — more flexible (e.g. regime-switching) but expensive to re-run at every rolling step.
Recommendation: Closed-form conjugate for the core rolling backtest; MCMC reserved for an optional richer model as an M9 addendum, off the critical path.
Status: OPEN.

**OD-9 — Entry/exit threshold policy**
*Affects: M7-T1.*
Options: fixed threshold (e.g. "enter if annualized funding > 20%") vs. Bayesian-credible-interval-based ("enter if P(cumulative funding > round-trip cost) > 80%").
Recommendation: Credible-interval-based — ties the Bayesian model's output meaningfully into the decision rather than using it decoratively.
Status: OPEN, leaning credible-interval.

**OD-10 — Position sizing / capacity model**
*Affects: M7-T2, M8-T3.*
Recommendation: Size until modeled marginal impact cost equals marginal expected funding edge — this directly produces the capacity curve that's the project's central output, rather than treating capacity as an afterthought.
Status: OPEN, leaning capacity-curve approach.

**OD-11 — Fee & funding settlement assumptions**
*Affects: M7-T4.*
Recommendation: Use the venue's historically accurate fee schedule and funding interval for the relevant symbol/date range (not current rates, if fees changed over time).

**Finding (2026-08-12): no machine-readable historical fee schedule exists.** Not in the archive;
`exchangeInfo` is geo-blocked; the venue's public fee page returns a challenge page rather than
content. There is no API for *historical* schedules even where the venue is reachable. This is not
a rounding detail — taker fees are of the same order as the funding edge, so the fee assumption can
flip the sign of the headline result.

Status: **RESOLVED 2026-08-12 — treat the fee as a swept parameter, with a manually sourced dated
schedule as the base case.** Concretely: commit a small dated fee table with citations for the base
case, and report the capacity answer as a function of fee level across a plausible range. This
converts an unavoidable data gap into a sensitivity result, which is a stronger artifact than a
hidden assumption, and it directly serves the project's "honest about limitations" stance.

The funding *interval* half of this decision is settled separately and cleanly:
`funding_interval_hours` is a per-row column in the source data (§3.3).

**OD-12 — Backtest validation methodology**
*Affects: M7-T3.*
Options: fixed train/test split vs. walk-forward/rolling re-calibration.
Recommendation: Walk-forward — more realistic, and the look-ahead unit test in M7-T3 becomes a concrete, demonstrable rigor artifact (directly addresses the "look-ahead bias" gap flagged in earlier resume feedback).
Status: OPEN, leaning walk-forward.

**OD-13 — Build tooling**
*Affects: M0.*
Recommendation: CMake + pybind11, Catch2 for C++ tests, pytest + ruff for Python, `uv` for environment management (consistent with existing workflow conventions).
Status: **RESOLVED 2026-08-12 at M0.** Adopted as recommended, with implementation details in `decisions.md` D-001 (scikit-build-core backend), D-002 (CMake/Ninja as venv dev deps), D-003 (`editable.rebuild` off), D-005 (Python pinned to 3.12), D-007 (GitHub Actions CI, Section 4.9), D-008 (`requires-python` narrowed to `>=3.12`).

**OD-14 — Data storage format**
*Affects: M0-T4, M1.*
Recommendation: Parquet via PyArrow as the storage format; DuckDB as an optional ad hoc SQL layer on top, no persistent server needed.
Status: **RESOLVED 2026-08-12 at M0-T4.** Adopted as recommended; Hive partitioning by `symbol`/`date`, with the data root overridable via `PERPCARRY_DATA_ROOT`.

---

## 7. Success Metrics

- Order book reconstruction validated against reference snapshots within a documented depth-level tolerance.
- Impact model shows a statistically meaningful, out-of-sample-validated relationship between order size and slippage (not just in-sample fit).
- Backtest produces a concrete, defensible capacity finding: a specific size (or range) at which net-of-cost P&L crosses zero, for at least one symbol — reported as a function of fee level, since no historical fee schedule is obtainable (OD-11).
- SPSC queue throughput benchmark documented with a specific events/sec figure.
- Look-ahead bias explicitly tested and ruled out via the M7-T3 poisoning test — this artifact alone directly answers a gap called out in prior resume feedback.
- The rigor artifacts are *enforced*, not just written once: the look-ahead poisoning test, fixed-seed determinism checks, and both build paths run in CI rather than depending on someone remembering to re-run them.
- Project is stoppable and coherent after M4 (systems core), after M7 (full research pipeline), or after M9 (polished writeup) — no single point of total failure.

## 8. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| R1 — Historical L2 data is unavailable or expensive | **Largely retired 2026-08-12.** Resolved via the vendor's free tier (OD-2d): true L2, no cost, same venue. Residual risk is coverage (12 days/year) and the vendor's free-tier terms, not availability. The original fallback (OD-2c) was found not to exist |
| R8 — An external assumption is wrong and is only discovered mid-implementation | Every external claim is verified by calling the service before the milestone that depends on it, and recorded in `external-dependencies-audit.md`. Four of the original assumptions were wrong; assume the next batch contains some too |
| R2 — Funding persistence signal turns out to be weak or absent | Not a failure mode — a rigorous "the edge doesn't survive realistic costs" finding is itself a valid, honest research result and arguably a *more* interesting one |
| R3 — Scope creep from trying to hit every technique at once | Milestones ordered so M0-M4 alone is a complete, demonstrable systems project; M5-M10 add research depth incrementally and can be paused after any milestone |
| R4 — pybind11 interop overhead undermines the "low-latency" story | Keep the C++/Python boundary at the pipeline level (post-SPSC-queue), not per-tick; benchmark and report interop overhead honestly rather than hand-waving around it |
| R5 — Altcoin liquidity ranking becomes stale by the time M8 runs | Defer symbol selection (OD-3) to build time rather than locking it in the design doc |
| R6 — Rigor claims (no look-ahead, determinism) silently decay after the commit that introduced them | Encode each as a CI check rather than a one-off manual verification (Section 4.9); a claim nothing re-runs is a claim about the past |
| R7 — CI becomes flaky or slow and stops being read | Network-dependent and long-running checks stay out of the per-PR tier; per-PR CI must remain fast enough that a red build is always believed |

## 9. Repository Structure

```
perpcarry/
├── .github/
│   └── workflows/
│       └── ci.yml         # lint + pytest + ctest, Linux & macOS
├── cpp/
│   ├── include/perpcarry/
│   │   ├── order_book.hpp
│   │   ├── book_replayer.hpp
│   │   ├── spsc_queue.hpp
│   │   └── impact_simulator.hpp
│   ├── src/
│   │   ├── order_book.cpp
│   │   ├── book_replayer.cpp
│   │   └── impact_simulator.cpp
│   ├── bindings/
│   │   └── pybind_module.cpp
│   ├── tests/
│   │   └── test_order_book.cpp
│   └── CMakeLists.txt
├── python/
│   └── perpcarry/
│       ├── ingestion/
│       │   ├── download.py          # shared HTTP fetch + checksum + extract (M0-T6)
│       │   ├── fetch_trades.py
│       │   ├── fetch_funding.py
│       │   ├── fetch_book.py
│       │   ├── derive_symbol_meta.py
│       │   └── validate_data.py
│       ├── models/
│       │   ├── impact_model.py
│       │   └── funding_model.py
│       ├── strategy/
│       │   ├── carry_strategy.py
│       │   └── backtest.py
│       └── reporting/
│           └── plots.py
├── tests/                 # pytest suite mirroring python/
├── data/                  # gitignored, local Parquet storage
├── notebooks/             # exploratory analysis
├── docs/
│   └── design-doc.md      # this document
├── pyproject.toml
└── README.md
```

## 10. Tech Stack Summary

- **C++17/20**, CMake, pybind11, Catch2, ThreadSanitizer (for M3-T2 concurrency validation)
- **Python 3.12+** (narrowed from 3.11+ to what CI actually exercises — see D-008), managed via `uv`; pandas/polars for data wrangling; statsmodels/scikit-learn for regression; PyMC (optional, M6 stretch) or hand-rolled conjugate updating for Bayesian inference; matplotlib/plotly for reporting
- **Storage:** Parquet via PyArrow, DuckDB as an optional query layer. Budget ~5.4 GB/year
  compressed for order book data at the one-day-per-month cadence; trades and funding are small.
  **Arrow C++ is deliberately not a dependency** — Python does all Parquet I/O and hands batches
  to the core over pybind11 (D-012), so the C++ side reads no files.
- **External data:** `data.binance.vision` S3 archive (trades, funding, klines) and the Tardis.dev
  free tier (`incremental_book_L2`, `book_snapshot_25`). Both are static file downloads over
  HTTPS — no venue API, no credentials, no rate-limit handling. An HTTP client is therefore a
  project dependency (M0-T6); the live venue API is unreachable from the development location.
- **CI:** GitHub Actions — ruff + pytest + `ctest` on Linux and macOS per push/PR; heavy checks
  (TSan, full backtests, reproducibility gate) deferred to a nightly tier. CMake and Ninja are
  installed as venv dev dependencies rather than system packages, so runners need only `uv`.

## 11. Glossary

- **ADV** — Average Daily Volume
- **bps** — basis points (1 bp = 0.01%)
- **Carry trade** — here, short perp / long spot (or index) to collect funding
- **Credible interval** — Bayesian analog of a confidence interval
- **Funding rate** — periodic payment between longs and shorts that anchors perp price to spot
- **L2 book** — order book aggregated by price level (vs. L3, individual orders)
- **Slippage** — difference between decision-time reference price and realized execution price
- **SPSC queue** — single-producer single-consumer lock-free queue
- **VWAP/TWAP** — volume-weighted / time-weighted average price execution strategies
- **Walk-forward validation** — backtest methodology where models only ever use data available at each historical decision point
