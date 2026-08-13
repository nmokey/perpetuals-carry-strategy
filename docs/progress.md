# Progress

Dated log of what actually happened. **Newest entry first.** Absolute dates only (`YYYY-MM-DD`) —
never "yesterday" or "last week". Record what was *verified*, not what was intended; anything
unverified belongs in `blockers.md` instead.

Milestone status at a glance:

| Milestone | Status |
|---|---|
| M0 — Scaffolding & environment | **Complete** (2026-08-12), T1–T6, CI green |
| M1 — Data acquisition | Specced, not started. Unblocked — OD-1/OD-2 resolved |
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

### All M1 open questions resolved — specs ready to implement

Licence read first, since it gated M1-T3. Every remaining question was then settled by measurement
rather than judgement.

**Licence (Tardis ToS, read in full).** Free samples fall under the standard terms; "Permitted Use"
is *internal business, research, educational or personal use*, so the project's core use is
licensed. Clause 9.2(2) forbids redistributing the Data, permitting only aggregated calculated
Derived Data from which raw data cannot be reconstructed. Practical effect: fitted coefficients,
capacity curves and plots are publishable; **raw book rows must never be committed, published, or
reach CI** — stricter than C9, and it rules out real vendor rows as test fixtures. One residual
ambiguity: publishing research findings is not expressly addressed, only redistribution of data.
Worth a confirmation email before M9; not a blocker before then.

**Measured resolutions.**

- **Volume reconciliation is exact, not approximate.** Summed trade quantity equals summed 1m
  `klines` volume with zero difference across `0GUSDT`, `DOGEUSDT` and `ETHUSDT` — the last with
  1.9M fractional-quantity trades, where float error was the plausible worry. Both float64 and
  `Decimal` agree. The criterion is now an equality in both the design doc and the specs.
- **Thin symbols settle every 4 hours, not 8.** BTC/ETH/DOGE are 8h; `0GUSDT` and `1000BONKUSDT`
  are 4h. OD-1's "8h for most symbols" is true for majors and false for exactly the class of symbol
  M8-T2 studies — anything hard-coding 8h would halve the altcoin's annualised funding.
- **A real upstream data gap**: `1000BONKUSDT` has 179 June settlements where 180 are expected, an
  8h hole after 2026-06-24 00:00 UTC. First concrete case for M1-T4's allowlist, and a better test
  fixture than anything synthetic.
- **Vendor days are UTC-aligned** — verified by downloading a full book day: 00:00:01.245Z to
  23:59:59.598Z, opening with a real `is_snapshot` block. Book and trade days align with no offset.
- **Book size scales steeply with liquidity**: 449 MB/day for BTCUSDT but **10 MB** for `0GUSDT`.
  Pulling several altcoin candidates is nearly free; the storage decision is about BTC alone.
- **Integrity signal for vendor files**: truncated `.gz` raises `EOFError` on inflation, so a
  partial download cannot pass silently. The vendor publishes no checksums.

**Decisions taken:** 24-month book window (2024-09 → 2026-08), trades continuous over the same span
plus a month of lead-in, funding fetched to contract inception, three disjoint days for tick
derivation, `data_quality_allowlist.yaml` for acknowledged gaps, validation nightly on non-vendor
fixtures.

**Correction.** The earlier claim that `0GUSDT`'s tick is `0.01` was wrong — a probe bug taking the
`min` of decimal exponents rather than the `max`, truncating precision 100×. It is `0.0001`,
reproduced across three disjoint days. Corrected in the audit, blockers and M1-T5. Exactly the
failure mode M1-T5's test 1 now pins: a plausible wrong number, not an error.

### M0-T6 implemented — the ingestion layer can now actually download

`python/perpcarry/ingestion/download.py`: streamed `fetch` with bounded retry, SHA-256
verification against the archive's published `.CHECKSUM`, `cached_fetch`, and `extract_csv` for
zip/gzip/plain. Added `httpx` (D-011) — the project previously had no HTTP client at all, which
blocked every M1 task. 18 tests; suite now 32 offline + 1 network.

Network tests are marked and **deselected by default** (`addopts = "-ra -m 'not network'"`), so CI
never depends on a live archive (C10). The one network test downloads a real funding archive,
verifies its published checksum, and asserts the 90-row/8h shape — it passes.

**Mutation testing found a decorative test.** `test_no_partial_file_survives_a_failure` used an
HTTP 500, which fails *before* any bytes are written — so no `.part` file ever existed and the test
passed even with the cleanup code deleted. It asserted nothing about the behaviour it was named
for. Replaced with a mid-stream failure that streams real bytes and then drops the connection.

Final result: **6/6 injected defects detected**, each by exactly one precisely-named test — better
targeting than the storage suite, where one defect lights up five tests.

Two notes for M1: the vendor publishes no `.CHECKSUM` files (404), so book downloads need a
different integrity signal — gzip inflation succeeding is the obvious candidate. And the mutation
harness must back up to a scratch copy rather than `git checkout` when the file under test is still
untracked; the first run silently accumulated all five defects instead of reverting.

### Design adjusted to the audit; OD-1, OD-2, OD-11 resolved

The audit's ten recommended edits are applied to `design-doc.md`, and propagated to the M0 and M1
specs. **Three open decisions closed** (D-009): Binance USD-M throughout, book data from the Tardis
free tier, fees as a swept parameter with a dated base-case table.

Design doc changes: §3.2 rewritten around the vendor's actual schema (adds `is_snapshot` and
`local_timestamp`, **drops `update_id`** — the feed has none, so dropped-update detection is
snapshot-comparison rather than sequence-based, and is weaker); §3.3 drops `mark_price` and adds
`funding_interval_hours`; §3.4 gains a storage footprint; §4.1 rewritten around static file
downloads with the geo-block stated; M1-T1/T2/T3 and M2-T2/T3 acceptance criteria rewritten to be
satisfiable; §7, §8 (R1 retired, R8 added), §9 and §10 updated.

**Two new tasks** (D-010), both dependencies the design never listed: **M0-T6** — the project has
no HTTP client at all, which blocks every M1 fetcher — and **M1-T5**, symbol tick/step derivation,
needed by M2, M4-T3 and M7-T2 with no obtainable authoritative source.

Specs now written: `M0/M0-T6`, `M1/M1-T1`, `M1-T2`, `M1-T3` (was Blocked, now unblocked), `M1-T4`,
`M1-T5`.

**Still open, both deliberately:** how many months of book data to pull (~449 MB/day compressed),
and the vendor's free-tier licensing terms, which have not been read and must be before the data
is relied upon.

### External-dependencies audit — 13 assumptions checked, OD-2 resolvable

`external-dependencies-audit.md` sweeps every claim the design doc makes about an external
service, each verified by calling the service from this machine rather than reading docs. Four
assumptions broken, two gaps needing a decision, and one finding that unblocks the project's
highest-risk dependency.

**The unblock:** Tardis.dev's free tier serves `incremental_book_L2` for `binance-futures` with no
API key — first day of every month, back to at least 2020, snapshot + diffs with `amount = 0` for
level removal, matching §3.2 exactly. Same venue as the deep trades/funding archive, so the project
keeps single-venue integrity *and* gets true L2. Sparse coverage is fine because M5 calibrates a
model and M7 consumes the model, never the raw book.

**Broken assumptions:** funding history has no `mark_price` (§3.3); "the venue's public endpoints"
(§4.1) are geo-blocked; M2-T2/M2-T3's "venue REST snapshot" and "exchange UI" validation routes are
unreachable — replaceable with Tardis `book_snapshot_25`; `trade_id` contiguity holds only for the
`trades` dataset.

**Two open decisions before implementation:** no machine-readable historical fee schedule exists
(B-006 — and taker fees are the same order as the funding edge, so this can flip the result's
sign), and symbol tick/step size has no specified source (B-007 — inferable from trades data by
GCD, verified, but currently specified nowhere).

Ten specific design-doc edits are listed at the end of the audit. Not yet applied — they change the
user's authored document and should be reviewed first.

### M1 specs written; two findings that change OD-2

Specs for all four M1 tasks are in `docs/specs/M1/`. Written against the venue's actual data rather
than its documentation — every claim below was verified by downloading and inspecting real files.

**M1-T1 (trades)** and **M1-T2 (funding)** are cleanly specified and unblocked: the Binance archive
carries both, is current through 2026-08-01, and is not geo-blocked. Concrete details that would
have been guessed wrong otherwise: the funding archive schema is `calc_time,
funding_interval_hours, last_funding_rate` — no `symbol`, and **no `mark_price`**, which Section
3.3 specifies; and settlement timestamps jitter by 1 ms, so naive integer-hour differencing reports
a phantom "7-hour" gap.

**M1-T3 (order book) stays blocked**, and the evidence changes the decision (B-005): OD-2 option
(c) does not exist as described. `bookDepth` is not an order book — it is cumulative depth at 12
percentage bands, ~30s sampling, no sequence numbers — and `bookTicker` (L1) was discontinued after
2024-03-30. There is nothing for the M2 replayer to replay, so "start with (c) to unblock M2" is
not an available path, and M1-T3's acceptance criterion is unsatisfiable under it.

Compounding that (B-004): **Binance's REST and websocket APIs are geo-blocked from this location**,
as is Bybit. OKX works and serves true L2 with `seqId`. So Binance is the better source for history
and an unavailable one for live capture. A fourth option not in the design doc — run the project on
OKX end to end — is now the most direct route to the stated criterion.

**M1-T4 (validation)** is specified with a note that the criterion's word "unexplained" requires an
allowlist of acknowledged gaps, or it is either unachievable or satisfied by weakening the checks.

### M0-T4 round-trip test strengthened

The partitioned round-trip test was weaker than its acceptance criterion. It coerced dtypes with
`.astype(...)` before comparing, and `assert_frame_equal` defaults to `check_exact=False`
(rtol 1e-5) — so it could see neither a dtype regression nor a precision loss.

Demonstrated concretely: with `write_parquet` silently multiplying every float by `1 + 1e-9`, the
**old suite reported 7 passed**. The rewritten suite fails 4 tests on the same defect.

Rewritten with exact comparison (`check_exact=True`, `check_dtype=True`), no coercion, and the two
real deviations asserted explicitly instead of silently corrected: partitioned reads move partition
columns to the end, and do not preserve row order across fragments. Added coverage for the Hive
on-disk layout (`symbol=.../date=...`, which Section 3.4 requires and nothing had checked), both
branches of the previously untested `overwrite` flag, and `dataset_path`. 7 tests → 12.

Verified by mutation rather than by passing: **4 of 4 injected defects detected** — float32
downcast, 1e-9 perturbation, partitioning ignored, `overwrite` ignored — each caught by at least
one test whose name identifies the cause; the clean tree passes 12/12.

Read the *detection*, not the failure count. One defect can trip five tests simply because every
test round-trips through `write_parquet`; that is overlap, not five independent checks. The
best-targeted mutation (`overwrite` ignored) produced the smallest count — a single failure in
`test_rewrite_is_idempotent_when_overwriting`. When debugging a storage regression, start from the
narrowest failing test name.

Lesson saved as C12, and M0-T4's acceptance criterion in the design doc sharpened to say *exact*
equality.

### CI pipeline added (M0-T5)

`.github/workflows/ci.yml`: two jobs — `python` (ruff, format check, pytest) and `cpp` (standalone
CMake configure/build/`ctest`) — each across `ubuntu-latest` and `macos-latest`. Rationale and the
tiering plan are in design doc Section 4.9; decisions in D-007.

Every step verified by running its exact command locally before commit. That caught a real defect:
`FETCHCONTENT_BASE_DIR` set as a workflow `env:` var does nothing, because CMake reads it only
from `-D`. As written it would have run green forever while caching an empty directory. Now passed
explicitly at configure time and confirmed to populate `.fetchcontent/`. Lesson saved as C11.

Also narrowed `requires-python` from `>=3.11` to `>=3.12` (D-008) — 3.11 was an untested claim —
and raised the CMake Python floor to match. `uv sync --locked` caught the stale lockfile
immediately, which is the check working as designed.

**First run green on all four jobs** — `python` and `cpp`, on `ubuntu-latest` and `macos-latest`
([run 31655822011](https://github.com/nmokey/perpetuals-carry-strategy/actions/runs/31655822011)).
The Linux legs mattered most: the project had only ever been compiled by AppleClang on arm64, and
it builds clean under GCC too. M0's acceptance criteria are now enforced per push rather than
verified once by hand.

### M0 re-verified from a clean clone

Prompted by a challenge to the "M0 complete" claim, all four criteria were re-run against a fresh
`git clone` rather than the working tree: build 114/114, `import perpcarry` + `perpcarry_cpp` OK,
`ctest` 1/1, pytest 9/9, ruff clean. Criteria hold as written.

Caveats surfaced in the process, now all addressed: the M0-T4 partitioned round-trip test coerced
dtypes unnecessarily and compared with a tolerance — **resolved**, see the entry above. The C++
core remains a deliberate stub (C5). And "passes" meant "passed once, on one Mac" — which is what
M0-T5 exists to fix.

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
