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
| OD-1 | Exchange/venue selection | **RESOLVED 2026-08-12** — Binance USD-M | M1 |
| OD-2 | Historical L2 book acquisition | **RESOLVED 2026-08-12** — Tardis free tier (option d) | M1-T3 → everything downstream |
| OD-3 | Symbol selection | **RESOLVED 2026-10-08** — BTCUSDT and SOLUSDT, D-026 | M8-T2 |
| OD-4 | Spot leg treatment | **RESEARCH POLICY OPEN** — explicit spot fills/quote fees implemented, D-037/D-038; historical execution, fee-asset and capital policy unadmitted | M8 research admission |
| OD-5 | Book reconstruction fidelity | **RESOLVED 2026-08-22** — L2, see D-017 | M2-T1 |
| OD-6 | Concurrency model | **RESOLVED 2026-08-29** — (b) single-threaded core + SPSC queue, see D-020 | M3-T2 |
| OD-7 | Impact model functional form | **UPDATED 2026-10-08** — primary square-root, linear diagnostic; D-026 retains D-024 caveats | M5-T2 |
| OD-8 | Bayesian inference method | **RESOLVED 2026-10-08** — closed-form Bayesian AR(1), D-026 | M6-T2 |
| OD-9 | Entry/exit threshold policy | **ENGINEERING RESOLVED 2026-10-10** — configurable Bayesian cost-adjusted gate and fixed-horizon exits, D-035; dated research parameter selection pending | Headline runs |
| OD-10 | Position sizing / capacity model | **ENGINEERING RESOLVED 2026-10-10** — constrained net-dollar optimum and separate supported break-even capacity, D-036 | Research evidence still gated |
| OD-11 | Fee & funding settlement assumptions | **ENGINEERING RESOLVED** — accounting and explicit fee sensitivities implemented, D-037; historical fee base case and exact funding marks remain unverified | M8 research admission |
| OD-12 | Backtest validation methodology | **RESOLVED 2026-10-08** — common 12-month walk-forward window, D-026 | M7-T3 |
| OD-13 | Build tooling | **RESOLVED 2026-08-12** — see D-001 | M0 |
| OD-14 | Data storage format | **RESOLVED 2026-08-12** — Parquet/PyArrow, DuckDB optional | M0-T4, M1 |

## D-025 — Bounded server rebuild and calibration gates (2026-10-08)

**Acquisition target superseded by D-026 later on 2026-10-08.** Retain its engineering work and
calibration gates, but do not resume the `0GUSDT` research backfill.

Rebuild from archives, with no transfer from the old machine. Start with `0GUSDT` trades/funding
2025-11 through 2026-09 and paired first-of-month book days 2025-12 through 2026-09. October 10's
daily and monthly archives independently reproduce the volume shortfall, so October stays out of
the accepted corpus. Ten book days are a target, not a claim of quality-checked coverage.
BTC is a daily-ingest sizing pilot; this does not resolve OD-3's final study-symbol selection.

M5-T1 requires content-matched quality reports, exact volume reconciliation for every prior ADV
day and the sampled day, and full-day independent book replay. It rejects missing days and
allowlisted failures. Sampling rounds the event grid to completed exchange milliseconds; sliced
simulation copies the entry replayer, including its snapshot-boundary state, and consumes future
updates only at each slice. This avoids rebuilding the whole prefix for every size while retaining
the M4 depletion and resync rules. Parameters and source/extension hashes travel with the dataset.

See `server-workflow.md` for reproduction commands and server-specific sanitizer handling.

## D-026 — BTC/SOL study scope and coverage before acquisition (2026-10-08)

The user fixes BTCUSDT/SOLUSDT, primary square-root impact regression, rolling Bayesian AR(1)
persistence gating, %ADV/notional capacity and gross/net-of-cost Sharpe. Stop `0GUSDT` expansion
and keep completed data for tests. The four quoted capacity/Sharpe/event figures are hypotheses.

Choose 2025-10-01 through 2026-09-30 as the common twelve-month scored window, preceded by
July–September warm-up and June volume prehistory. Calendar selection precedes fitting and
performance inspection. Archive probes establish availability, not completeness. Resolve OD-3,
OD-7's primary form, OD-8's initial inference method and OD-12; OD-9's threshold/horizon/exit details
and OD-4/OD-10's accounting/sizing decisions remain open.

Monthly sample books are full-day feeds on only 12 scored days per symbol. Full daily L2 replay
needs additional historical access; a continuous public-data backtest with inferred cost estimates
must be labeled separately. The user is choosing headline execution fidelity. Continue funding,
price, trade and sampled-book acquisition/validation independently. Preserve M0–M4 and route M5
reconstruction through the existing SPSC queue before isolated cost simulation.

See `btc-sol-study.md` and `config/btc-sol-study.toml` for the exact coverage and claims ledger.

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

**Superseded in part by D-008** (2026-08-12): `requires-python` narrowed to `>=3.12`. The 3.12
pin itself stands.

**Revisit when.** The scientific stack has settled 3.13/3.14 wheels and there is a reason to move.

---

## D-006 — PyMC deliberately not a dependency (2026-08-12)

**Context.** OD-8 lists MCMC as an option for the Bayesian funding model.

**Decision.** Not installed. The critical path uses hand-rolled closed-form conjugate updating;
PyMC would only appear if the optional M9 MCMC addendum is actually pursued.

**Why.** Keeps the rolling backtest cheap enough to re-run at every walk-forward step, and keeps a
heavy dependency out of the environment until it is earned.

---

## D-007 — GitHub Actions CI, two jobs, two platforms (2026-08-12)

**Context.** M0's acceptance criteria were verified once by hand, on one machine. Nothing
re-checked them, and nothing exercised the standalone CMake path at all.

**Decision.** `.github/workflows/ci.yml` runs two jobs — `python` (ruff, `ruff format --check`,
pytest, via `uv sync --locked` which also compiles the extension) and `cpp` (standalone CMake
configure/build/`ctest`) — each on `ubuntu-latest` and `macos-latest`. Design rationale is written
up in design doc Section 4.9.

**Why this shape.**

- Both build paths run, because D-001 created two of them and only CI can keep them in step.
- Ubuntu is included because every line so far has only been compiled by AppleClang on arm64.
- `uv sync --locked` fails when `pyproject.toml` changed without re-locking, keeping `uv.lock`
  honest. This fired immediately on the D-008 change, as intended.
- CMake/Ninja being venv dev deps (D-002) means runners install nothing beyond `uv`.
- Catch2 is redirected to a stable `FETCHCONTENT_BASE_DIR` so `actions/cache` has something at a
  fixed path to cache. **Note:** CMake does not read that variable from the environment — it must
  be passed with `-D` at configure time. An env-var-only version silently cached nothing.

**Deferred.** Nightly tier (TSan for M3-T2, full backtests for M8, reproducibility gate) is
specified in Section 4.9 but not built — there is nothing to run yet, and scaffolding CI for
code that does not exist is convention C5 applied to infrastructure.

**Cost.** Repo is public, so Actions minutes are free on all runners including macOS. Jobs carry a
15-minute timeout so a hang fails fast rather than sitting on a runner.

**Accepted risk.** Third-party actions are pinned to major tags (`actions/checkout@v4`,
`astral-sh/setup-uv@v6`, `actions/cache@v4`) rather than commit SHAs, so a compromised tag would
execute in CI. Acceptable here: the workflow has `permissions: contents: read`, holds no secrets,
and publishes nothing. Revisit if CI ever gains a token, a secret, or publish rights — in
particular if OD-2 resolves to a paid vendor whose API key lands in repository secrets.

---

## D-008 — `requires-python` narrowed to `>=3.12` (2026-08-12)

**Context.** The project declared `>=3.11` while `.python-version` pinned 3.12. Nothing had ever
run on 3.11 — the claim was untested.

**Decision.** Narrow `requires-python` to `>=3.12` and raise the CMake `find_package(Python ...)`
floor to match, rather than adding a 3.11 leg to the CI matrix.

**Why.** Nothing in the project needs 3.11, so supporting it means maintaining a matrix leg to
defend a capability nobody wants. Prefer a narrow claim that is true to a broad one that is
unverified. Supersedes the `>=3.11` half of D-005.

**Revisit when.** Someone actually needs to run this on 3.11.

---

## D-009 — Data sourcing settled: Binance archive + Tardis free tier (2026-08-12)

**Context.** The external-dependencies audit found four of the design doc's remote assumptions
broken. OD-1, OD-2 and OD-11 were all resolved together because they turned out to be one
question.

**Decision.** Binance USD-M for the whole project. Trades, funding and klines from
`data.binance.vision`; L2 order book from the Tardis.dev free tier
(`incremental_book_L2` + `book_snapshot_25`, first day of every month). No venue API is used —
it is geo-blocked and unnecessary. Fees become a swept parameter with a dated base-case table,
since no historical fee schedule is machine-readable anywhere.

**Why this combination.** It is the only one giving deep funding history *and* true L2 *and* a
single venue. OKX is reachable and has live L2 but only ~3 months of funding history, which would
gut M6. Binance's own free book datasets are unusable (`bookDepth` is percentage buckets;
`bookTicker` was discontinued in 2024-03).

**Consequences accepted.**
- Book coverage is 12 days/year, not continuous. Tolerable because M5 fits a model and M7 consumes
  the model, never the raw book — but it means impact cannot be conditioned on same-day book state
  during the backtest.
- No `update_id` in the vendor feed, so dropped-update detection is snapshot-comparison rather than
  sequence-based. Strictly weaker; §3.2 now says so.
- The project cannot be extended to live trading from this location without changing venue.
- ~5.4 GB/year compressed for book data.

**Still open.** How many months to pull, and the vendor's free-tier licensing terms — which have
**not** been read and must be before the data is relied upon.

---

## D-010 — New tasks M0-T6 and M1-T5 (2026-08-12)

**Context.** Two dependencies the design doc never listed, both surfaced by the audit.

**Decision.** Add **M0-T6** (HTTP client + shared download/checksum/extract helper — the project
had no HTTP client at all, blocking every M1 fetcher) and **M1-T5** (symbol tick/step size derived
by GCD over observed trades, since `exchangeInfo` is geo-blocked, the archive has no metadata, and
the vendor's instruments API is paid-only).

**Why they were missed.** Both are the kind of dependency that is invisible until you try to write
the code — which is the argument for writing specs before implementing, not after.

---

## D-011 — `httpx` as the HTTP client; cache under the data root (2026-08-12)

**Context.** M0-T6 needed a client; the project had none.

**Decision.** `httpx`, with the download cache at `data/.cache/` via `download.cache_dir()`.

**Why.** `httpx` streams cleanly, has sane timeout defaults, and is well maintained. `requests`
would also have worked — this is not load-bearing, and is recorded only so it is not
re-litigated. The cache goes under the data root because that is already gitignored and already
relocatable via `PERPCARRY_DATA_ROOT`; re-downloading a 449 MB book day on every run is slow
enough that people start commenting out the download.

**Retry policy.** Transport errors and `{408, 425, 429, 5xx}` are retried with linear backoff;
every other 4xx fails immediately. This matters for the vendor: a 401 means "not the first of the
month" and a 404 means "no archive for that day" — both are caller errors, and retrying them
just makes a mistake slower to discover.

---

## D-012 — Python reads Parquet; the C++ core never touches storage (2026-08-20)

**Context.** B-002. §2's architecture diagram drew the storage layer feeding the C++ core
directly, but §10's tech stack listed no Arrow C++ / Parquet dependency. Nothing fails until
someone tries to implement that read — it blocks whichever of M2-T2 / M3 first needs the core to
consume stored data.

**Decision.** Python owns all Parquet I/O. `BookReplayer` is fed rows across the pybind11
boundary; the C++ core gains no Arrow dependency, no Parquet dependency, and no file I/O.

**Why.** Three reasons, in order of weight:

1. **It is what the boundary rule already says.** Risk R4 puts the pybind11 boundary at the
   pipeline level, post-SPSC-queue, never per-tick. A batch of book rows handed in once per replay
   is exactly that; a C++-side file reader would be a second, redundant entry point into the same
   data.
2. **Arrow C++ is a heavy dependency for one function.** It would land in the wheel build, in the
   standalone CMake path, and in both CI legs on two platforms — to do something PyArrow already
   does in the process that wrote the file.
3. **The alternative buys nothing measurable yet.** The performance argument for a native reader
   is real only if Parquet decode shows up in an M10 profile. It has not been profiled, and M10 is
   a stretch milestone. Deciding on a guess now costs more than revisiting it with data later.

**Cost, stated plainly.** Feeding rows across the boundary means the replay input is materialised
in Python before it crosses, so peak memory is bounded by batch size rather than by streaming
decode. For the one-day-per-month cadence (449 MB/day compressed for BTC, 10 MB for a thin
symbol) that is acceptable, but it is a real ceiling and it is the thing to measure first if
replay throughput disappoints.

**Reversible.** If M10 profiling shows the boundary dominating, adding Arrow C++ behind the same
`BookReplayer` interface is an additive change — no caller moves.

**Follow-through.** §2's diagram now routes the storage → core edge through the Python layer.
M2-T2 and M3-T1 specs should state that the replayer's input is an in-memory batch, not a path.

---

## D-013 — book timestamps normalised to ms; capture latency kept in µs (2026-08-20)

**Context.** M1-T3. The vendor emits `timestamp` and `local_timestamp` in **microseconds**;
§3.2 says normalise to milliseconds to match every other dataset in §3. But the gap between the
two columns *is* the vendor's observed capture latency, and §3.2 does not say what unit
`local_timestamp` ends up in — normalising one and not the other leaves two columns in different
units on the same row, and normalising both quantises the gap.

**Decision.** Both columns are stored in milliseconds. The difference is computed from the raw
microsecond values *before* the conversion and stored as a third column, `latency_us`.

**Why, with the measurement.** On 0GUSDT 2026-06-01: p1 1.48 ms, median 2.04 ms, p99 516 ms.
So the latency is *not* sub-millisecond, and converting first would not erase it — but **99.8% of
rows are not a whole number of milliseconds**, so the microsecond detail would be lost on
essentially every row. One extra int64 column is a cheap price for not throwing that away, and the
alternative (mixed units per row) is the kind of thing that produces a wrong number two milestones
later with nothing to point at.

**Note for M9.** This latency is the *vendor's* capture latency, not the exchange's. It bounds what
the data can support: a median of ~2 ms with a 516 ms tail is not a basis for latency-sensitive
claims, which the design doc already says the project does not make.

---

## D-014 — `book_snapshot_25` is melted to long form on ingest (2026-08-20)

**Context.** M1-T3 specified `book_snapshot_25` as the independent reference for validating replay
(M2-T2), and implicitly assumed it shared `incremental_book_L2`'s shape. **It does not**, and the
spec did not say so — discovered when the first real ingest failed with "missing columns ['amount',
'is_snapshot', 'price', 'side']". It is a **wide** 104-column table: one row per book image, with
`asks[0].price` … `bids[24].amount` as separate columns.

**Decision.** Melt it on ingest to one row per level: `timestamp, local_timestamp, latency_us,
side, level, price, quantity`, stored under `data/book_snapshot/`.

**Why.** It shares a vocabulary with every other dataset in §3; M2-T2's "replayed top-25 match the
reference" becomes a join on `(timestamp, side, level)` rather than a reshape of 104 bracketed
column names; and DuckDB can query it without quoting every identifier.

**Two consequences worth stating.**

1. Melting multiplies row count by up to 50, so the read chunk size is divided by the same factor
   for this dataset — otherwise the bounded-memory property is lost exactly where the files are
   largest. Measured: 0GUSDT 2026-06-01 is 277,590 images → 13,879,500 rows, 11.0 MB on disk.
2. **Empty trailing levels are dropped**, because a book thinner than 25 levels leaves them blank
   and a level that does not exist is not a level with an unknown price. This is the *opposite* of
   the incremental feed's `amount = 0`, which is meaningful and must be preserved. Conflating the
   two conventions would either invent phantom levels here or destroy removals there.

**Depth is read from the columns, not assumed to be 25.** The dataset is named for 25 levels;
trusting the name over the file is how a silently truncated schema gets ingested.

---

## D-015 — `trade_id` contiguity is not a venue invariant (2026-08-20)

**Context.** M1-T1's acceptance criterion, the audit's assumption A7, `fetch_trades.backfill`'s
hard refusal, and M1-T4's continuity check all rested on "`trade_id` is contiguous in the `trades`
dataset". Building the first real corpus for M1-T4 hit it immediately: `backfill` refused
`0GUSDT` 2026-06 with **154 gaps**.

**The measurement.** 154 gaps across 2,366,674 trades — 157 absent IDs, every run 1 or 2 long, no
duplicates, no time discontinuity around them. Then the decisive independent test: on 2026-06-01
(4 gaps) and 2026-06-15 (6 gaps), summed trade quantity equals summed 1m `klines` volume
**exactly**. IDs are skipped; trades are not lost.

**Decision.** Contiguity is dropped as an invariant. `fetch_trades.MAX_ID_SKIP = 8` separates
venue id-skips from suspected data loss: runs at or below it are counted and reported, runs above
it fail. The threshold is an early-warning heuristic — **the completeness guarantee is the klines
reconciliation**, which is exact and independently sourced.

**Why not allowlist them.** 154 per symbol-month is systematic behaviour, not an incident. The
allowlist exists for gaps someone investigated and found benign; an entry regenerated every month
would be a rubber stamp, and would drown the one real entry it already holds.

**Why not just drop the check.** A wholly missing day is still a boundary jump of tens of
thousands, which this still catches — and that is the failure the check was really for. Keeping a
loosened version costs nothing and preserves the detection that matters.

**The general lesson.** An invariant confirmed on a sample is a hypothesis, not a property. A7 was
verified against a 200-row fixture and a handful of days; the first full month falsified it. Where
an invariant is load-bearing, either verify it at the scale it will be relied on or write the code
to measure it rather than assume it.

**Applied to.** Design doc M1-T1 criterion, audit A7, `fetch_trades`, `validate_data`.

---

## D-016 — the data-quality allowlist is TOML, not YAML (2026-08-20)

**Context.** M1-T4's Q2 resolved to a committed `data_quality_allowlist.yaml`.

**Decision.** Same file, same contents, TOML instead — `data_quality_allowlist.toml`.

**Why.** YAML would mean adding PyYAML as a runtime dependency for one small config file, whereas
`tomllib` is in the standard library from 3.11 and the project already pins 3.12 (D-005/D-008).
TOML keeps the comments the file needs — its whole purpose is prose reasons reviewable in diffs —
and matches the project's existing config language. The spec named YAML as a format, not as a
requirement; nothing else depends on the choice.

---

## D-017 — OD-5 resolved: L2 price-level reconstruction (2026-08-22)

**Context.** OD-5 sat at "leaning resolved (L2); confirm before M2-T1" since 2026-08-12. M2-T1's
`Depends On` names it, so it had to be confirmed rather than assumed before the spec was written.

**Decision.** L2 — price-level aggregated. Confirmed, not merely leaned.

**Why the design doc's reasoning is weaker than the real one.** §6 argues L2 on grounds of "matches
realistically available data and is standard practice". True, but the actual constraint is harder:
after OD-2 the project's only book source is Tardis `incremental_book_L2`, which **is** price-level
aggregated at the source. No order-level data exists in any dataset this project can reach, at any
price tier that was evaluated. L2 was never a choice between two available fidelities, and the
writeup should say so rather than presenting it as a considered trade-off it did not get to make.

**Consequence, and it is a real limitation.** Queue position is unknowable from aggregated data.
M4's simulator can therefore model *marketable* orders — walking the book and paying the spread —
but cannot model a resting limit order's fill probability. That bounds the strategy in M7 to
market-order execution, and it belongs in the M9 caveats alongside the partial-depth and
frictionless-spot approximations, not as a footnote.

**Consequence for the code.** `OrderBook` keys on price and stores one aggregate quantity per
level. There is no order id anywhere in the core, and adding one later would not be additive — it
would be a different data structure fed by a different feed.

---

## D-018 — M2 validates against vendor data through a local CSV harness, not through Python (2026-08-22)

**Context.** M2-T2's acceptance criterion is "replayed state matches the vendor's
`book_snapshot_25`". Two standing constraints make the obvious route unavailable:

1. **D-012** — the C++ core reads no Parquet and does no file I/O; Python reads and feeds batches
   across the pybind11 boundary. But the bindings are **M3-T1, which depends on M2-T2**. The data
   path the criterion assumes does not exist at the moment the criterion is checked.
2. **Tardis Clause 9.2(2)** — book rows may not be committed or reach CI. So this comparison can
   never be a CI test, in the per-PR tier *or* the nightly one, whatever the mechanism.

**Decision.** A local-only validation harness, outside `perpcarry_core`:

- `python -m perpcarry.tools.export_book` exports one symbol-day from the Parquet corpus to two
  CSVs (events in file order; long-form reference images), writing under `data/` by default.
- `perpcarry_replay_validate`, a C++ tool target, reads those CSVs, replays, and compares.
- Committed artifact is the **JSON summary** — counts and mismatch rates. Aggregated and
  non-reconstructible, so licence-clean; the CSVs and the corpus stay out of git as always (C9).

**Why not pull M3-T1 forward.** It inverts the doc's dependency edge and violates C5 — bindings
built to serve a test, before the milestone that specifies them, is exactly the "half-finished M3
living inside M2" that destroys per-milestone demonstrability. The harness is small, and when
M3-T1 lands the same validation re-runs through Python (M3-T3's smoke test), at which point the
harness is a debugging convenience rather than the only route.

**Why CSV rather than teaching the core to read Parquet.** That is D-012, unchanged. The tool has
file I/O; `perpcarry_core` still has none, and nothing links Arrow.

**The C10 tension, stated rather than hidden.** C10 says a rigor claim CI does not run is a claim
about the past, and this claim is exactly that: the real-data comparison is a dated local run. The
licence leaves no version of it that CI may execute. What CI *can* enforce, and will: the harness
builds, and runs end to end against a **synthetic** events+reference pair with a known injected
defect. So the mechanism is continuously tested and only the input is manual. Logged to
`blockers.md` so the gap is visible at M9 rather than rediscovered there.

---

## D-019 — the replay criterion asserts on every image, not only unambiguous ones (2026-08-29)

**Context.** M2-T2's spec partitioned the comparison points and asserted only on the
*unambiguous* subset — images whose millisecond holds exactly one event, where the pairing
between image and diff is forced and needs no assumption. That was derived a priori from
`0GUSDT`, where 105,142 of 277,590 images (37.9%) qualify.

**It does not survive contact with a liquid symbol.** Measured 2026-08-28 on `BTCUSDT`
2026-06-01: **zero** of 287,193 images are unambiguous. At ~1.9 events per millisecond
every image shares its millisecond with several events, so the criterion as written cannot
be evaluated at all on the symbol M2–M4 actually replays. A criterion that is vacuous
exactly where it matters most is not a criterion.

**Decision.** Passing requires zero mismatches across **all** images. The unambiguous count
is still computed and reported, because it is the part that is sound with no assumption at
all; `Inconclusive` is now reserved for a run that compared nothing.

**What this assumes, stated plainly.** That the vendor emits a `book_snapshot_25` image only
after applying every update sharing that exchange millisecond. Evidence: **564,783 images
across two symbols, zero counter-examples** — `0GUSDT` full day (277,590) and `BTCUSDT`'s
first 20M events (287,193). Note that this includes 459,641 ambiguous images that the
original criterion would not have looked at, all of which matched exactly.

**Note the direction.** This makes the check *stricter*, not looser — it asserts on images
it previously only counted. If the assumption is ever false, a run fails loudly and gets
investigated. That is the safe way to be wrong, and it is the opposite of widening a
tolerance until the data fits.

**What did not change.** Equality is still exact, with no epsilon, on price and quantity
alike. The original spec's reasoning for that stands and is untouched.

**Two findings from the same run, both kept rather than smoothed over:**

1. **Only the top 25 levels are validated at all.** A deliberately dropped update at
   `0.3997` — deep in a ~1000-level book — was replayed wrongly and the harness passed,
   because no reference image describes that depth. The same experiment against the
   most-updated price (`0.4204`, top of book) produced 10 mismatches, correctly categorised.
   So the check is real, and it constrains ~2.5% of the book by level count. M4 walks far
   deeper than that for large orders. Logged to `blockers.md`.
2. **A dropped update self-heals.** Those 10 mismatches stopped once the next update at
   that price arrived: L2 diffs carry absolute quantities, not deltas, so a lost row
   corrupts the book only until that level is next touched. Reassuring about the data's
   robustness, and a reason the detection window is narrower than it looks.

---

## D-020 — OD-6 resolved: single-threaded core plus an SPSC queue (2026-08-29)

**Context.** OD-6 sat at "OPEN, strongly leaning (b)" since 2026-08-12. M3-T2's `Depends On` names
it, so writing the spec required confirming it rather than inheriting the lean.

**Decision.** Option (b). A deterministic single-threaded book core, with a lock-free
`SPSCQueue<T>` decoupling the ingestion/replay thread from the simulation thread.

**Option (c) is not merely unearned — it cannot be evaluated honestly here.** The design doc rejects
a fully concurrent book on the grounds that the complexity "isn't earned". The sharper reason is
that a backtest replays *one totally ordered event stream*: there are no concurrent writers, so
per-price-level locking would be protecting the book against contention its input is incapable of
producing. Any throughput number measured for it would describe a workload this project never runs.
That is worse than unnecessary — it is a benchmark that invites a false claim.

**Option (a) was the real competitor, and it loses on one specific ground.** Fully single-threaded
is correct, simpler, and costs nothing the research results care about. What it gives up is the one
place the project has a genuine systems boundary to model. (b) is chosen because the
feed-handler → strategy-engine split is a real structure in real systems, not because concurrency
makes the backtest faster.

**What this must not do to determinism, stated as a constraint rather than a hope.** Reproducibility
given a fixed seed is a north-star invariant, and putting a queue between replay and simulation is
exactly the kind of change that quietly breaks it. The queue is permitted to change *when* an item
is consumed; it must never change *which* items are consumed or *in what order*. SPSC FIFO preserves
order exactly, so the constraint lands entirely on the consumer: **no simulation behaviour may
depend on queue occupancy, on how many items are available in a batch, or on producer timing.** A
consumer that, say, sized an order by how far behind it had fallen would produce results that differ
between runs on the same input. M3-T2's spec makes this a test, not a comment.

**Honest framing for M9, decided now rather than at writeup.** In a backtest the producer is reading
a file, so the queue is not on a latency-critical path in any live sense. The defensible claim is
that the *structure* mirrors a real boundary and that its throughput is measured; the indefensible
one is that it makes the backtest low-latency. The writeup says the former.

**Consequence for the code.** Unchanged for the core: `OrderBook`, `BookReplayer` and the M2-T3
renderers stay single-threaded and lock-free by virtue of being untouched by threads. The queue is
new surface, not a modification of existing surface — which is why this decision costs nothing to
have deferred until now.

---

## D-021 — M4 reports how deep a walk went; it does not cap at the validated depth (2026-08-30)

**Context.** The replay is validated against `book_snapshot_25`, so only the top 25 levels of a
~1000-level book are constrained by any independent reference (D-019). M4-T1's book walk goes
deeper than that for exactly the large orders the capacity answer is about. There is no deeper
reference on the free tier, so this cannot be fixed by getting better data.

**Decision.** Walk the full book, and report `levels_consumed` and `beyond_validated_depth` on every
fill. Do not truncate the walk at level 25.

**Why capping would be worse than the problem.** Truncating makes a large order look *cheaper* than
it is — it stops paying for depth precisely where depth gets expensive — so the error runs in the
flattering direction. Worse, it would bound the capacity answer by an artifact of the reference
dataset rather than by the market, while looking like caution.

**Why a flag rather than a caveat in the writeup.** An average price from a deep walk is
indistinguishable from one from a shallow walk. Recorded per fill, the approximation survives into
M5's calibration dataset and M9's capacity curve, where the large-order end can be split out and
shown for what it is. Stated once in a document, it would be invisible next to the number.

**What this does not claim.** The deep book is not validated by this. It is *disclosed*. The
residual risk stays on the watch list, and the honest framing for M9 is that the large-order end of
the capacity curve rests on replayed state no independent source constrains.

---

## D-022 — ADV is computed from the trades corpus and cross-checked against Binance klines (2026-08-30)

**Context.** M4-T3's criterion is "unit tested against known ADV figures", and no known figures
exist: the venue API is geo-blocked (B-004), so the only ADV available is one derived from our own
`trades` corpus. Testing that against itself is the failure mode M1-T4 shipped and M3-T3's
"checkpoint" nearly repeated — two copies of one assumption, agreeing by construction.

**Decision.** ADV is computed from the `trades` corpus, and validated against the **daily klines**
published on `data.binance.vision`, whose `volume` column is the venue's own aggregation of the same
trades. A minimal `fetch_klines.py` joins the ingestion package; `binance_archive.klines_daily_url`
already exists from M1-T1 and is reused rather than restated.

**Why not use klines as the source.** M5 and M7 consume the `trades` corpus, so the ADV that feeds
calibration has to come from those same rows — otherwise the study is calibrated against one dataset
and executed against another. Klines check the computation; they do not replace it. Same reasoning
as D-018: validate the thing you actually use.

**What the check would catch that nothing else does.** A trades ingest that silently dropped rows.
Every existing check is internal — schema, contiguity, partition dates — and all of them pass on a
corpus that is simply missing data the venue had. An independent volume total is the first thing in
this project that could notice.

**Tolerance is deliberately not chosen here.** It gets set from a first measurement and the observed
difference recorded, because a tolerance picked before seeing the discrepancy is a tolerance picked
to pass. If the two agree exactly, assert exactly — M2-T2's experience is that the strict criterion
is more often available than expected.

---

## D-023 — a sliced order consumes the liquidity it takes (2026-08-30)

**Context.** M4-T1's `simulate_market_order` is read-only by design: M5 sweeps many sizes against a
single instant, so simulating must not consume the book. M4-T2 then executed each slice through it,
and a test written for something else caught the consequence — four slices of 5 units at one
timestamp each saw an undepleted book and filled at the same average as one slice of 5. A 20-unit
parent was therefore *cheaper* than a single 20-unit order. Free money from relabelling.

**Decision.** Slices consume. `execute_market_order(OrderBook&, ...)` performs the same walk and
then depletes what it took — full levels removed, a partial level reduced. `simulate_market_order`
stays const and unchanged. A test pins both, so neither can quietly become the other.

**Why this is the conservative direction.** Not consuming makes large orders look cheaper the more
finely they are sliced, without bound, which is exactly the error a capacity study must not make.
Consuming makes a split order cost the same as an unsplit one at the same instant, which is the only
self-consistent answer.

**The approximation, stated.** A later vendor update at a touched price carries an *absolute*
quantity (§3.2), so it overwrites whatever the footprint left behind. Our hypothetical order's
impact therefore decays as the real book refreshes. This is crude — the historical data describes a
world in which we did not trade — but it is decay taken from the data rather than assumed, and it is
the mechanism that makes spreading an order over time genuinely cheaper in M4-T2 rather than
cheaper by construction. It belongs in the M9 caveats with the other stated approximations.

**Cost.** `BookReplayer` gained a `mutable_book()` accessor, narrow in intent and not in signature:
nothing stops a caller corrupting replay state with it, and nothing but the sliced simulator should
use it. The replay statistics are unaffected — they count rows applied, not levels present.

---

## D-024 — OD-7 resolved: fit both functional forms, and report per size regime (2026-08-30)

**Context.** OD-7 offered linear (Almgren-Chriss-style), square-root, or both. M5-T2's `Depends On`
names it, so it had to be confirmed before that spec could be written.

**Decision.** Fit both, and report the comparison **per size regime** rather than declaring a single
winner. The design doc anticipated the first half; the second half comes from the data.

**Choosing a form a priori would be the exact thing this project exists not to do.** The claim is
"execution costs are calibrated, not assumed". A functional form picked before looking is an
assumption in the most load-bearing place in the model, and the comparison is a deliverable in its
own right rather than a step toward one.

**The M4 probe already shows a single exponent will not do.** Fitting `slippage ~ size^alpha`
pairwise across the M4 sweep on `0GUSDT` 2026-06-01 (mean over 259 instants):

| size range | implied alpha |
|---|---|
| 100 → 1,000 | 0.197 |
| 1,000 → 10,000 | 0.411 |
| 10,000 → 50,000 | 0.506 |
| 50,000 → 200,000 | 0.768 |
| 200,000 → 1,000,000 | 1.167 |

Square-root law is alpha = 0.5, linear is 1.0. The exponent **climbs monotonically across the
range**, so neither law describes the whole curve and a single-form fit would be a compromise that
is wrong at both ends. Three things are going on, and they should be modelled rather than averaged:

1. **Small sizes are dominated by the half-spread**, which is a constant offset and not a power law
   at all — it compresses the apparent exponent toward zero. This is measurement, not market: those
   figures are slippage against the *mid*.
2. **The mid-range sits close to the square-root law** (0.41–0.51), which is what the literature
   predicts and is mild evidence the simulator is behaving.
3. **Large sizes go super-linear** (1.167), consistent with an order eating into progressively
   thinner book.

**Two consequences for M5-T2, both non-obvious and both easy to get wrong.**

*Fit against touch-relative slippage, not mid-relative.* `Fill` reports both (M4-T1). The
half-spread is a separate cost component that M7 accounts for on its own; regressing on mid-relative
slippage folds it into the impact coefficient, which double-counts it downstream and, as the table
shows, distorts the exponent most exactly where impact is smallest.

*The super-linear region is the least trustworthy part of the curve.* At 200,000 units 94.2% of
fills walk past the validated depth, and at 1,000,000 it is 99.6% (D-021). So the regime where the
data most clearly departs from the square-root law is the regime where the underlying book is not
independently validated. That is not a reason to discard it — it is the region a capacity answer
lives in — but any reported coefficient for it carries that caveat, and M9 must not present the
large-order end with the same confidence as the small.

**Not a finding yet.** Six discrete sizes, one symbol, one day, means rather than a fit, and against
the wrong reference price for this purpose. It is enough to establish that the comparison is worth
running and that a single form will not win outright; it is not the answer M5-T2 produces.

## D-027 — Preserve the fixed window when BTC/SOL data fail admission (2026-10-08)

Both 2025-10-10 daily trade archives fail exact volume/ID integrity checks. Retain checksum-verified sources for diagnostics but do not store them as accepted trades, allowlist the defects, relax tolerance or move the study dates. If recovery fails, evaluate a separately documented alternative ADV source before changing the trade-derived contract. SOL early/late inferred tick grids disagree; preserve the metadata combiner's rejection and require dated regimes rather than pooling into a timeless finest tick. BTC metadata agrees across three study-spanning dates and its evidence is refreshed. Sampled-book 429 Retry-After is respected; it does not change the independent daily-access decision.

## D-028 — Record execution alternatives without selecting one (2026-10-08)

The user requested a record of the discussed considerations, options and tradeoffs. Added
`btc-sol-data-options.md` and linked it from the study plan. Book reconstruction uses snapshots
and incremental book updates; executions alone cannot recover additions/cancellations. Tardis
alone can support a sampled-day execution study, while %ADV and carry need additional volume,
funding and price coverage. Existing Binance histories remain useful without merging trades
into book replay.

Full-year historical L2 access, sampled-book inferred costs, sampled-day execution, funding/price
cost-sensitivity prototypes and prospective collection are documented as alternatives. One-day
fits are pilots; later time-block and whole-day tests are required before generalization claims.
Tardis's free live software runs locally and connects to exchange feeds, so it does not resolve
this server's restricted snapshot endpoint or provide the missing historical year.

**No research mode was selected.** The common window, pending headline coverage, trade-derived
ADV contract, BTC/SOL scope, preserved 0G testing data and untested numerical claims are unchanged.
Adopting bar-volume ADV or an inferred-cost headline requires an explicit documented choice.

## D-029 — M5-T2 fit boundaries, regimes and signed targets (2026-10-09)

Implemented equal eligible-row weighting and pooled fits with per-training-day coefficient
diagnostics; separate symbol/side/schedule/depth fits. Explicit training/test date cutoffs
prevent later data from shifting a prior fold. Default training is the prior 90 calendar
days. Size bins use training-only quantiles of unique ADV fractions, not claimed market
regime breakpoints. Square-root remains primary; linear and log-OLS power are diagnostic.
Power fitting counts nonpositive targets omitted from logs but evaluates all held-out
targets in original bps. Crossed/exhausted rows are explicitly excluded.

Signed slippage is retained without clipping: price changes can favor sliced fills, and
a synthetic C++ static walk at 123.45 for 0.0001 quantity measured approximately
-1.15e-12 bps from floating arithmetic. Negative fitted cost coefficients are reported
and flagged as unsuitable for a nonnegative impact law. Undefined R², missing regimes
and too few days do not become flattering diagnostics or fallback coefficients.

Calibration admission binds manifests, Parquet hashes and current source quality evidence.
Read fragments directly without inferring Hive schema from paths, and check read stability.
Residual artifacts stay ignored; M5-T3 remains responsible for versioned model save/load.
The implemented fitting code is tested with synthetic laws; actual BTC/SOL fits remain
blocked by missing eligible calibration partitions. Headline coverage choice and ADV
source contract are unchanged.

## D-030 — Strict per-symbol impact artifacts and explicit fold retention (2026-10-09)

Adopt M5-T3's one-file-per-symbol JSON recommendation, with schema 1 and no migrations.
Separate fold directories retain immutable inputs for later backtests; the fitting CLI
exports only when `--model-dir` is supplied. No fabricated BTC/SOL coefficient file is
committed to demonstrate the loader. Synthetic fixtures explicitly identify provenance.

Store evaluated coefficients with depth/size identities, signed-target usability,
source hashes, fitting date/code revision, train/test days/counts and limitations.
Unavailable strata remain coverage caveats, never fallback coefficients. Summed
provenance counts cover all-size square-root strata once; diagnostic forms and size
bins overlap. Loading validates exact nested fields and numeric/chronological
consistency without accessing raw data or refitting. Model selection and causal
application to strategy decisions remain M7 responsibilities.

## D-031 — Library helpers own ingestion/replay evidence; tools orchestrate (2026-10-09)

Research and ingestion libraries must not import command-line tools. Extract reusable
book partition discovery/schema, ordered Parquet streaming, batch conversion, content
hashing and UTC calendar helpers into their owning library modules. Existing public
tool/helper imports can remain aliases for compatibility; new callers use the library.
Corpus reports consume calibration admission without a reverse dependency cycle.

Statistical fitting and fixed-model loading must import without the C++ replay extension;
only calibration admission imports the C++-dependent generator. Offline architecture
tests enforce both rules. Keep code/schema behavior stable during organization cleanup;
defer broad validation-module splits until growth warrants them and preserve check order.

## D-032 — Funding EDA is descriptive; prior windows remain separate (2026-10-09)

M6-T1 uses the complete funding-specific corpus/evidence, independently of blocked
book/ADV calibration. Keep original timestamps and declared intervals; separate
contiguous constant-cadence segments rather than pooling unequal settlement lags.
Use predeclared 24-lag ACF/PACF, intercept-only ADF/AIC and KPSS/auto with 5% significance.
Record both opposing nulls and KPSS table bounds. Short/constant cases are unavailable.

Full-warmup/full-study diagnostics describe data; they cannot tune historical priors,
thresholds or model orders. Monthly diagnostics use the 90 days strictly before each
cutoff. Neither stationarity non-rejection nor lag-one correlation establishes AR(1)
adequacy. Preserve signed funding tails, censored positive-run caveats and the distinction
between simple fixed-notional funding sums and actual strategy P&L. M6-T2/T3 own Bayesian
fitting, posterior checks and rolling forecasts.

## D-033 — Conjugate funding baseline and explicit adequacy failure (2026-10-09)

M6-T2 models settlement bps as intercept plus phi times previous settlement plus Gaussian
innovation. Condition on the first observation; use a joint Normal-Inverse-Gamma prior
(mean zero, precision I, shape 3, scale 2 bps²) and exact coefficient/variance updates.
The prior is proper and configurable in the library, not estimated from the study year.
Preserve phi outside the stationary interval and report its probability; no clipping,
long-run mean assumption or silent cadence pooling. The diagnostic command rejects cadence
changes; causal regime resets belong to M6-T3.

Separate in-sample conditional replication (fixed observed lag design, shared joint draws)
from frozen warmup-posterior, one-step holdout diagnostics. Report all coverage, residual
ACF/PIT and negative-tail checks without selecting a favorable metric or refitting until
it passes. Synthetic correctness is not empirical adequacy. Warmup checks are plausible,
but study uncertainty is undercalibrated; this does not block building T3's rolling logic,
and it does prevent calling the model a validated strategy gate. Prior sensitivity and
causal predictive calibration remain required before downstream strategy claims.

## D-034 — Causal rolling funding and recursive horizon checks (2026-10-10)

M6-T3 refits the conjugate model on observed settlements in a timestamp-based 90-day
window, each settlement, rather than reusing posteriors as priors or subtracting unstable
quadratic sufficient statistics. Retain at least 30 settlements within one cadence regime.
Reject ordering/gap defects without state mutation; cadence changes clear the old segment
and require fresh history. A decision cannot predate admitted history or be stale by more
than one cadence plus five seconds. One instance represents one symbol. Historical
availability assumes the observation is known when update is called; event time alone
does not prove a live-feed latency contract.

Cumulative forecasts recursively simulate joint parameter/variance draws fixed per path
and independent innovations per future step. Horizon is a count of settlements. Preserve
unrestricted phi, explicit nonfinite failure, fixed-notional fraction units, seed and
approximate probability Monte Carlo error. Finite sample moments do not establish
existence of all long-horizon theoretical moments.

Predict before admitting the current settlement, score realized funding in a separate
retrospective pass. Diagnostic horizons 3 and 21 represent one day/week only at current
8h cadence; these are not OD-9 holding choices. Exclude incomplete/cadence-crossing
outcomes and report the counts. Compare frozen and rolling fits using identical initial
history; reset the comparator on regime change. Prior variance/precision variants are
predeclared sensitivity checks, not a default selection based on holdout outcomes.

Rolling one-step calibration improves but cumulative weekly checks fail. Keep B-012
open; M6 engineering completion does not certify a strategy gate or close OD-9.

## D-035 — Cost-adjusted carry decisions and admission (2026-10-10)

Resolve OD-9 mechanics as a configurable short-perp/long-spot policy. Require explicit
holding-settlement count, entry probability and lower continuation probability; no
headline parameter set is selected from M6 study results. Historical policy selection must
use information preceding the scored run. Test choices (3, 0.8, 0.5) exercise branches only.

Enter when both P(cumulative funding > entry + terminal close + financing) strictly exceeds
the entry threshold and expected net funding is positive. For held positions retain the
original horizon and subtract actual settlements held; never reset it on a new decision.
Continue against the alternative of closing now: hurdle = terminal close - close now +
remaining financing. Sunk entry costs and realized funding do not enter that comparison.
Exit intent on maturity, cadence change, unavailable/unadmitted evidence, nonpositive
expected incremental edge or probability at/below continuation threshold. Intents do not
execute orders, change position state or claim successful closure without data.

Bind M6 predictions to symbol and model/configuration digest (inference sources, prior,
rolling window, minimum history). Require matching past adequacy evidence, cadence,
horizon and expiry. Approval is caller-supplied evidence, not an automatically certified
verdict; no real BTC/SOL approval exists while B-012 is open. Deterministic Monte Carlo
probabilities remain approximations, and synthetic branches establish mechanics only.

M5 cost adapter requires both nonnegative square-root sell/open and buy/close laws,
explicit supported schedule/size stratum and caller-declared inside-validated order depth.
Reject extrapolated size, missing law, future validation evidence and changed artifact
hash. Full held-out end, not just training cutoff, must precede the historical decision.
File generation date records reproducibility, not simulated information availability.
Add touch-relative impact, half-spread, fees and explicit hedge costs once; convert bps
by 10,000. No flat-cost fallback. Synthetic admission defaults off in both adapter and
strategy. Caller owns dated fee/spread/hedge/depth inputs and admitted ADV/notional.

Terminal close initially uses today's close-cost estimate (stationary costs); the pure
interface accepts another estimate known at decision time. Never use the realized future
book to choose an entry. Sizing/metadata/ADV admission belongs to T2; actual fills, funding
cashflows, changing exposure and capital accounting belong to T3/T4. OD-4, OD-10 and
B-009–B-012 remain open. This completes T1 engineering, not M7 or a profitable backtest.

## D-036 — Marginal-impact sizing and executable capacity bounds (2026-10-10)

Resolve OD-10 by maximizing expected net funding dollars for a flat short-perp/long-spot
candidate. With base-ADV fraction x, notional N=P*A*x, summed square-root coefficient K
in fraction units, expected cumulative funding mu and fixed proportional costs b,
profit=N*(mu-b-K*sqrt(x)). Marginal cost is b+1.5*K*sqrt(x), not average impact. Continuous
optimum [(mu-b)/(1.5*K)]^2 and zero-profit root [(mu-b)/K]^2 answer different questions.

Restrict executable lots to both sides' common calibrated range, explicit validated
liquidity, maximum notional/ADV fraction, dated contract minima and Decimal lot step.
Binary search the largest size passing the unchanged T1 entry gate; compare adjacent
lots around the bounded continuous optimum. Choose smaller on an exact profit tie and
zero when no feasible profitable admitted lot exists. Zero impact still has finite caps.
Report chosen size, feasible maximum and supported break-even separately in ADV and
notional. Label outside-support roots without extrapolating capacity. An external cap
is not a measurement of true economic capacity, and expected dollars are not realized P&L.

Shared `costs.load_curve`/`from_curve` retain T1 provenance, chronology and support checks
without repeated disk loads. Charges are explicit, including hedge costs; terminal close
uses today's costs. `SizingInputs` carries caller-admitted complete prior 30-day UTC base
ADV and dated contract evidence/digests. The validated quantity cap covers entry and the
modeled close envelope, without guaranteeing future depth. No loader certifies manually
supplied hashes or manufactures BTC/SOL metadata, fits or funding approval. B-009–B-012
and OD-4 stay open; dated policy selection and real-input admission remain research gates.

Correct the existing accounting sequencing defect: T4 depends on T1/T2 and OD-11 and
precedes T3; T3 depends on T2/T4 and OD-12. Task IDs and acceptance criteria are retained.
Next is hand-reconciled T4 accounting, then T3 walk-forward integration.

## D-037 — Economic settlement accounting and explicit fee evidence (2026-10-10)

Implement T4 as a pure immutable Decimal ledger for long spot and short linear USDT
perpetuals. Independent executed fills change each leg's quantity/basis; no fictional
derivative sale proceeds. Funding cash = minus signed current perp quantity times actual
settlement mark times signed rate. Positive funding pays shorts; negative funding debits
them. Gross uses the same actual quantities at reference-mid executions, with identical
funding marks, before explicit fees/financing. Net uses actual fills and cash. Impact and
spread present in execution prices are not deducted again as estimated costs.

Require an explicit next-funding boundary and consume each settlement in order, even
flat. Normalize/validate archive jitter before ledger admission. Per-row cadence advances
the next boundary under the declared in-force schedule; an announced calendar change
must be supplied by T3 before affected fills, without future rate use. Reject perp fills
within 15 seconds on either side of a funding boundary: nominal ordering cannot establish
exact venue eligibility inside the documented timing uncertainty. This conservative guard
restricts the executable path and must be reported, rather than advertised as venue replay.

Fees are taker USDT equivalents on executed notional; base-asset/BNB inventory, discounts,
rebates and exchange commission rounding are not simulated. The cited 2026-10-10 table
uses current spot 0.10% and a hypothetical futures 0.05% illustration as study sensitivity
assumptions. It does not certify those historical rates. Default admission rejects
assumptions; verified records require evidence known by the fill time. OD-11 remains
resolved as a methodology, while its historically defensible research base case is not
cleared. Source URLs and effective/observation dates are explicit in config and the spec.

Capital is explicit, and negative cash is visible; no automatic financing, margin
reservation or liquidation. This is economic P&L accounting, not a venue wallet model.
OD-4 and B-010 still require fee-asset treatment, funding marks and collateral/capital
admission policy. In particular complete trade-price minute bars cannot replace funding
settlement marks. T3 owns input admission/calendar/execution integration; M8 owns Sharpe
and fee sensitivity reporting. T4's synthetic reconciliation completes engineering only.

## D-038 — Causal integration and explicit execution scenarios (2026-10-10)

M7-T3 consumes one event at a time, without sorting or reading future suffixes. Warmup
only fits funding. At each scored boundary settle the actual position at the actual
funding mark, then admit that observation to M6. One decision follows at a configured
delay (example 16 seconds), forecasting future settlements. The delay is an availability
assumption outside T4's guard, not historical publication-latency evidence. Require the
constant declared cadence and complete decision calendar; unsupported cadence changes
fail pending a dated adapter. Preserve the original holding budget through each update.

Use impact artifacts sealed for monthly UTC folds, with complete validation preceding
fold start. CLI artifacts must fit entirely inside the prior configured impact window;
90 training days plus later validation cannot be passed off as a 90-day total window.
Funding approval remains explicitly scoped to model, horizon, symbol and dates. Independent
valuation marks and actual settlement marks are required; trade-price bars do not silently
substitute. Library evidence is caller admitted; digest fields are not raw-source audits.

Execution is an explicit scenario: inferred side-specific impact/spread with spot charges,
or full paired C++ market walks on copied consumer checkpoints for both legs. Book walks
are static counterfactual fills without persistent footprint in subsequent vendor updates.
Neither backend manufactures missing books or settles B-009's headline methodology.
Partial or unsupported fills cannot turn an exit intent into a fictional flat position.

Bound entry by spot cash, adverse execution costs and a fixed derivative collateral
fraction. Recheck proposed fills and require cash plus marked perp P&L to cover reserve
at funding and valuation events. Shortfall aborts; no maintenance-margin/liquidation model.
Fees remain quote-equivalent scenario inputs under D-037, with explicit expected versus
realized financing. These mechanics do not close OD-4 or historical B-010 accounting gates.

The CLI labels engineering runs, preserves earlier output on later errors, rejects output
overwrite and marks truncated coverage incomplete. Completion needs the full funding and
decision path plus an end-exclusive-minus-one-millisecond valuation; it may retain an
open position. This is not daily-return coverage, research adequacy or Sharpe certification.
M8 owns metrics and fee sensitivity after B-009–B-012 and dated research inputs are cleared.

## D-039 — User-selected monthly-calibrated inferred execution (2026-10-10)

The user explicitly excluded continuous daily book acquisition because access and storage
are unsuitable for this study. Headline BTC/SOL research retains the common 12-month window
and uses continuous funding/prices with inferred execution costs calibrated only on
completed prior monthly sample days. Finish the currently authorized 15 book days per
symbol (three warmup, twelve scored), including top-25 references. Preserve C++ replay
and ingestion/consumer queue separation. Do not expand regular-day L2 acquisition.

This resolves the B-009 methodology choice, not sample replay, impact-model validation or
headline research readiness. Report modeled execution, sparse independent-day evidence,
spread/hedge assumptions and stress sensitivity. No Sharpe/capacity target is forced.

Existing complete minute bar partitions contain base and quote volume. Assess bar-derived
ADV before bulk raw-trade acquisition; this is an alternative awaiting an explicit
implemented and validated input contract, not permission to silently substitute or hide
the October 10 trade-archive discrepancies. Historical settlement/valuation marks, fee
and contract evidence remain acquisition/admission requirements under B-010/B-011.

## D-040 — Explicit exact bar-volume ADV for the active study (2026-10-10)

Use the already acquired Binance USD-M minute-bar base volume for the BTC/SOL study's
ADV denominator, explicitly labeled `futures_bars`. Full raw trades are no longer an
acquisition prerequisite for this method. Recheck original ZIPs against the recorded
published checksums, complete ordered UTC grids and source identity; sum original
decimal text and average the 30 completed UTC days preceding the decision's UTC day.
All 487 days and 457 warmup/study feature windows per symbol were validated, with
exact matches against the four existing admitted pilot reports.

This is an explicit alternative to D-022, whose raw-trade default remains intact. M5
opts in with `--adv-source futures_bars`; downstream fit admission regenerates the
same evidence. Preserve independent book replay, book partition freshness and quality
gates. M7 uses the feature and dated window/hash through existing sizing inputs.
Keep the causal fingerprint independent of future monthly archive/report checksums;
retain those hashes separately as offline admission provenance. Archive verification
is not proof of exact historical publication latency.

October 10 rejected raw trades remain rejected, and their measured deficits are
retained. Sparse cross-checks do not prove every volume total correct. Do not mix
spot volume with perpetual ADV or silently accept a corrupted trade corpus. D-039's
inferred execution scope still requires admitted prior impact/funding models, settlement
marks, fee/contract evidence and an actual research input manifest before M8 results.
