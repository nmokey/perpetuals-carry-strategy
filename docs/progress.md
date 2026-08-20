# Progress

Dated log of what actually happened. **Newest entry first.** Absolute dates only (`YYYY-MM-DD`) —
never "yesterday" or "last week". Record what was *verified*, not what was intended; anything
unverified belongs in `blockers.md` instead.

Milestone status at a glance:

| Milestone | Status |
|---|---|
| M0 — Scaffolding & environment | **Complete** (2026-08-12), T1–T6, CI green |
| M1 — Data acquisition | **Complete** (2026-08-20), T1–T5 |
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

## 2026-08-20

### M1 complete — T4 data validation, and a broken invariant it exposed

`ingestion/validate_data.py` plus the committed `ingestion/data_quality_allowlist.toml`. 43 tests;
suite now 251 offline + 6 network, all green. **26/26 mutations caught.** 15 checks across
integrity, completeness, consistency, plausibility and the order book.

**Validated against a real assembled corpus**, not just fixtures: 0GUSDT June 2026 — 30 trade days
(2.37M trades), 30 funding days (180 settlements), one book day (1.3M rows) and its reference.
**354 checks, zero failures**, including the exact klines volume reconciliation on all 30 days.

**The headline finding: `trade_id` contiguity is not a property of this venue, and never was.**
Building that corpus was the first time a *full month* went through `fetch_trades.backfill`, and it
refused immediately — 154 gaps in 0GUSDT 2026-06. Characterised: 157 absent ids across 2,366,674
trades, every run 1 or 2 long, no duplicates, no time discontinuity. The decisive test was the
independent one — on 2026-06-01 (4 gaps) and 2026-06-15 (6 gaps) summed trade quantity equals
summed 1m klines volume **exactly**. Ids are skipped; trades are not lost.

So the design doc's M1-T1 criterion was unsatisfiable, audit assumption A7 was false, and both the
fetcher and this validator were enforcing a rule real data does not obey. All four are corrected
(D-015): gaps are now classified against `MAX_ID_SKIP`, with the klines equality carrying the
actual completeness guarantee. The general lesson is the one worth keeping — **an invariant
confirmed on a sample is a hypothesis, not a property.** A7 had been checked against a 200-row
fixture and a few days; the first full month falsified it.

**A second bug, and this one my tests were actively hiding.** The validator located funding
partitions with `fetch_funding.DATASET`, which is `"fundingRate"` — the *archive's* name, appearing
in URLs. The fetcher stores under `funding/`. So the validator looked in a directory that never
existed, found zero partitions, and reported everything fine. It passed the whole suite, including
a test whose stated purpose was that every check actually runs, because **the fixture had hard-coded
the same wrong path**. It only surfaced when a real corpus was pointed at it.

Fixed structurally rather than by correcting the constant: both fetchers now export a `STORAGE_DIR`
the validator reads, and the fixture builds its corpus by calling the fetchers' own `store()`
functions, so a future divergence fails loudly. Recorded as C15.

Also corrected: the allowlist is TOML rather than the spec's YAML (D-016) — `tomllib` is stdlib
where PyYAML would be a new runtime dependency for one config file. And the book schemas now keep
the vendor's `exchange` column, which was previously discarded; it is the only venue-tagged field
anywhere in the corpus, and without it the spec's "a mixed-venue corpus is rejected" test had
nothing to test. The validator is explicit that trades and funding cannot be checked this way and
reports those as skipped rather than passed.

**The pre-push audit found the checksum check was a no-op**, which is the finding worth keeping
because of what it was a no-op *about*. `archive_checksums` built its URL as
`{BASE}/{filename}` — but the archive nests by period, dataset and symbol
(`{BASE}/monthly/trades/0GUSDT/...`), so every request 404'd, `fetch_checksum` returned `None` for
a missing `.CHECKSUM`, and the loop skipped the file. All 42 cached archives were skipped, the
check yielded **zero results**, and the report read clean.

That is precisely the false confidence the module's own docstring is about — written into the one
check whose entire job is integrity. It survived because nothing tested the opt-in network path,
and because a check that yields nothing looks identical to a check that yields all-passes.

Fixed by reconstructing the URL from the filename (`binance_archive.url_for_filename`, which has
to handle klines naming their *interval* where every other dataset names itself), and by making an
unverifiable file a **reported failure** rather than a silent skip — being unable to verify a file
is not the same as the file being sound. Verified against the real cache: 42 archives, 42 results,
all passing, where it previously produced none.

**Network checks are opt-in and reported as skipped, never as passes** — archive checksum
re-verification and the klines reconciliation both need a live host, and a gate that silently
reports success without running is the false confidence this task exists to prevent.

### M1-T3 complete — historical L2 order book acquisition

`ingestion/fetch_book.py` + `ingestion/tardis_archive.py`. 61 tests (59 offline, 2 network); suite
now 204 offline + 6 network, all green. **19/19 mutations caught.** This is the data the project's
central claim rests on — that execution costs are *calibrated* rather than assumed — so the
fidelity obtained here bounds what M9 may honestly assert.

Verified against real vendor data (0GUSDT 2026-06-01): 1,299,113 incremental rows in 3 chunks,
19,799 snapshot rows, 63,764 removals, 13 resync events; and 277,590 book images melted to
13,879,500 reference rows. 10.2 MB + 11.0 MB on disk.

**Two spec assumptions were wrong, and both failed loudly only because a guard existed.**

**`book_snapshot_25` is not shaped like the incremental feed.** The spec listed it as the
validation reference without saying it is a **wide 104-column table** — one row per book image with
`asks[0].price` … `bids[24].amount` as columns — not one row per level update. The first real run
died with "missing columns ['amount', 'is_snapshot', 'price', 'side']". It is now melted to long
form on ingest (D-014), which turns M2-T2's comparison into a join rather than a reshape of 104
bracketed names. Melting multiplies rows by up to 50, so the read chunk shrinks by the same factor
for that dataset — otherwise the bounded-memory property is lost exactly where the files are
largest.

**Every vendor URL for a symbol ends in the same basename.** The date lives in the path
(`.../2026/06/01/0GUSDT.csv.gz`), and `cached_fetch` keys its cache on the filename — so a 24-month
backfill would have downloaded June once and served that same file for all 24 months, and for both
datasets. Silent, and it survives every schema and integrity check. The Binance archive never
exposed this because its filenames carry the date. Caught by the stray-day guard, which existed for
an unrelated reason: a mismatched day tripped it, and the mismatch was the cache. `cache_path` now
builds the key from dataset, symbol and date, and three tests pin it.

Worth recording as the general lesson: **a guard written for one failure mode caught a different
one.** The stray-day check was defending against misfiling rows into the wrong partition; what it
actually found was a caching bug two layers away. Cheap invariants pay out in places you did not
plan for.

**Two things the review then corrected, both about honesty of reporting rather than correctness.**

`resyncs` counted *rows*, not events. A real resync is one ~1,400-row book image, so the day read
as "18,396 resyncs" when the true figure is **13**. Nothing computed a wrong number, but M2 reads
this field to decide how often its replayer must reset state, and three orders of magnitude is not
a rounding difference. Now `resync_events` and `resync_rows`, with a test that a block split across
a chunk boundary still counts once.

And the docstring justifying D-013 claimed the vendor's capture latency is "frequently
sub-millisecond". Measured, it is not: p1 1.48 ms, median 2.04 ms, p99 516 ms. The decision to keep
`latency_us` still stands, but for the accurate reason — **99.8% of rows are not a whole number of
milliseconds**, so converting first loses the detail on essentially every row. The claim now matches
the measurement.

**Licence handling.** Every fixture in the test module is synthetic, which is a licence requirement
rather than a style choice: Clause 9.2(2) forbids redistributing raw rows, and committing a real
book day would publish vendor data through the repo and push it into CI. There is a test asserting
no vendor book fixture is ever committed, and the two tests that touch real vendor data are marked
`network` so they never run in CI (C10).

**Not done, deliberately.** The 24-month bulk pull. The spec's Q1 says to exercise the pipeline on
a few months before committing to ~10.8 GB for BTC, and that is now possible — but it is a large
download and belongs in a deliberate run, not a side effect of finishing the task.

### M1-T5 complete — symbol tick/step derivation

`ingestion/derive_symbol_meta.py` plus the committed `ingestion/symbol_meta.json`. 48 tests (47
offline, 1 network); suite now 144 offline + 4 network, all green. **14/14 mutations caught.**
Resolves B-007, which had been blocking M2, M4-T3 and M7-T2 with no obtainable authoritative
source.

**The pre-push audit found the confidence logic was counting its own evidence wrong**, and this is
the finding worth keeping. `combine` pooled windows by **summing** their per-window distinct
counts, so a price observed on all three days counted as three pieces of evidence. The threshold
it feeds is justified by a probability argument over *distinct* values, so the error inflated
confidence — and it inflated it most where the windows overlap most, which is precisely where they
are least independent. Wrong direction, quietly.

It also meant the committed `distinct_prices` field did not hold a distinct count, and a second,
smaller version of the same bug sat underneath: deduplication was on the CSV *text*, so an archive
emitting both `1.0` and `1.00` would have counted one grid point twice.

Fixed by carrying the distinct observations themselves through `GridEstimate` and pooling by union,
with dedup on numeric value. The corrected counts, re-derived: `BTCUSDT` 68,703 → 65,187 distinct
prices, `ETHUSDT` 30,995 → 26,835, and quantities roughly halved (`ETHUSDT` 99,215 → 49,412) since
trade sizes repeat across days far more than prices do. **No tick or step value changed and all
three symbols remain confident by a wide margin** — the conclusions were never at risk, but the
reported evidence was overstated by up to 2x.

Worth noting what did *not* catch it: 12/12 mutations, a full suite, and a network test that
agreed with hand-verified values. Every one of those checks the value; none checked whether the
number attached to *how much we should believe it* meant anything. The two mutations added for the
pooling logic now do.

**The re-derivation reproduced the spec's hand-verified table exactly** — tick, step, per-window
distinct-price counts and trade counts, for both `0GUSDT` and `ETHUSDT` across all three days.
That is the strongest available evidence the implementation matches what was measured by hand on
2026-08-12, since the spec's numbers were produced by a different throwaway probe.

Added `BTCUSDT` (tick `0.1`, step `0.001`, 11.7M trades, 65,187 distinct prices) — it is the
symbol whose book data M2–M4 replays, and the design doc never listed its tick as a dependency
either. Symbol coverage stops there deliberately: OD-3 is open and deferred to M8, so the table
grows when the study symbols are chosen.

**Two bugs found by the tests, both mine, both silent-wrong rather than loud.** The dtype guard
checked `dtype != object`, which is right for pandas 2 and wrong for pandas 3 — this project runs
3.0.5, where `read_csv(dtype=str)` yields `StringDtype`, so the guard rejected every real archive
frame. Now it checks the *element* type, which is the property actually meant. And `sample_days`
built its month midpoint from 1-based month numbers, putting the middle window a month late and,
on a single-month range, inventing a second window *after* the end date.

**Design notes worth carrying forward.**

- `decimal_gcd` **rejects** floats rather than converting them. A silent conversion is exactly the
  bug that produces a plausible number and no error, and `Decimal(0.1)` is not one tenth.
- Scaling is done on the digit tuple, not `scaleb`, so the active decimal context cannot round a
  long price on the way through.
- Confidence is pooled across windows, not judged per window: three thin days that agree are
  better evidence than any one of them. Below 20 distinct values the estimate is reported
  low-confidence, and `--write` refuses to commit it.
- Cross-window disagreement is an **error**, never resolved by taking the finest value. Two
  different causes produce it — a window too thin to resolve the grid, or the venue re-ticking the
  symbol mid-study — and they call for opposite responses.

**The mutation run's one survivor was a rendering choice, and closing it needed a different kind
of test.** Dropping `normalize()` leaves the step size as `1.0` where the grid is `1` — numerically
identical, so no equality assertion can see it, and my first attempt at a test read the *committed
file*, which already held the normalised text and passed either way. The test that catches it pins
the rendering of a freshly derived value. Worth remembering: when the property under test is how a
value is *written* rather than what it *is*, asserting against the stored artifact tests nothing.

Verified: 141 offline + 4 network green, ruff clean, and the committed JSON confirmed present in a
built wheel (`wheel.packages` carries package data, but a missing lookup table would only surface
at M2).

### Blocker sweep, and B-002 resolved as D-012

No code changed. Suite re-verified before and after: **97 offline passed, 3 network deselected**,
`ruff check` and `ruff format --check` clean.

**B-006 was stale and had been for eight days.** It sat in Active claiming to be "the main open
item before implementation" — but OD-11 resolved it on 2026-08-12, the same day it was raised,
via exactly its own recommended path (fee as a swept parameter, manually-sourced dated base-case
table). Nothing was wrong with the decision; the blocker just never got swept when the OD closed.

Filed the general lesson with it: **resolving an OD does not close the blockers that cite it.**
`blockers.md` is read as steering at the start of a session, so a false Active entry costs a
future session real time — it is worse than no entry.

**B-002 resolved as D-012** — Python owns all Parquet I/O; the C++ core takes an in-memory batch
across pybind11 and does no file I/O at all. This was the adjacent gap: §2's diagram drew storage
feeding the core directly while §10 listed no Arrow C++ dependency, and nothing would have failed
until M2-T2 or M3 tried to write the read.

Chosen over adding Arrow C++ because it is what Risk R4's pipeline-level boundary already implies,
because Arrow C++ would land in the wheel build, the standalone CMake path, and four CI legs to
duplicate what PyArrow does in the process that wrote the file — and because the performance
argument for a native reader is a guess until an M10 profile exists. The cost is stated rather
than hidden: replay input is materialised before it crosses, so peak memory scales with batch
size. Reversible behind the same `BookReplayer` interface if profiling ever justifies it.

Propagated so the documents no longer disagree: §2's diagram routes storage → core through a
Python replay driver, §2's rationale and §10's storage bullet state the no-file-I/O rule, and
`CLAUDE.md`'s "five known gaps" line now reflects the two that are actually still open.

**Active blockers are now B-004 and B-007 only** — B-004 a standing constraint rather than a task,
B-007 resolved by implementing M1-T5.

---

## 2026-08-12

### Stale documentation swept

Retired advice and statuses that later findings had overtaken:

- **The "start a recorder now, every day of delay is lost data" urgency is withdrawn** from
  `blockers.md` and the audit. It was correct only while OD-2 option (a) was live; every source the
  project now uses is a static historical archive, so nothing decays while a decision is pending.
  The residual argument against dawdling is precedent, not decay — `bookTicker` was published for
  ten months and then simply stopped.
- **B-001, B-003 and B-005 moved to Resolved** with their resolutions recorded. B-004 (geo-blocking)
  stays Active as a standing constraint rather than an open task — nothing in scope needs the live
  API.
- **Three watch-list items retired** as done: CI has run and is green, network tests exist and are
  marked, and M1-T1's `trade_id` criterion was settled by naming the `trades` dataset.
- **Funding cadence corrected everywhere** — audit A12, design doc §3.3, M1-T2's spec. Earlier text
  said majors are 8h and thin symbols 4h; `0GUSDT` actually ran 4h → 1h → 4h within a year, so the
  interval is not a per-symbol constant and must be read per row.
- **Added a watch-list entry for M6**: an AR(1) fit over a window whose sampling frequency changes
  mid-way is not sampling one process throughout. Better raised in M6-T2's spec than found at fit
  time.
- `CLAUDE.md` and `README.md` now state what actually exists and works, including that nothing needs
  to run continuously.

### M1-T2 complete — funding rate downloader

`ingestion/fetch_funding.py`, reusing `binance_archive.py` and `download.py`. 28 tests (27 offline,
1 network); suite now 90 offline + 3 network, all green. 10/10 mutations caught.

Both fixtures are real archive months so the hard cases are genuine: `BTCUSDT` 2026-06 exhibits the
actual ~1 ms jitter, and `1000BONKUSDT` 2026-06 carries the real upstream gap found during the
audit. A test asserts the fixture still jitters — if the source stops, the tolerance it justifies
would be silently untested.

**Mutation testing led to deleting a branch rather than testing it.** The first implementation
measured each settlement step against the *earlier* row's interval, which misreads a 4h→8h
re-cadence as a missing settlement, and compensated with a skip for pairs straddling a change. No
test could distinguish that skip present or absent. Measuring against the **later** row — the
cadence the settled period actually ran under — is correct in both directions with no special case.
A test now fails if the choice is reverted.

Worth noting as a pattern: a mutation surviving is not always a missing test. Sometimes it means
the branch has no behaviour worth having.

**The review then found the completeness check skipped itself on exactly the interesting months.**
It compared settlement count against `24 / interval × days`, defined only for a single cadence — so
any month containing an interval change passed with no coverage check at all. Found by running it
against `0GUSDT`'s real listing month: **233 settlements where a full month allows 180**, accepted
without complaint.

That month also produced a data finding worth carrying into M6/M8: **`0GUSDT` settled every 4h at
listing (2025-09-17), then every 1h from 2025-09-22**, returning to 4h by 2026-06. The cadence is
not a symbol constant, let alone a global one. Hard-coding 8h would misstate a 1h symbol's
annualised funding by 8×.

Completeness is now **continuity plus endpoint coverage**, which holds whatever the interval mix.
A late start is legitimate and reported; a short end is a defect. The exact-count check is kept
where meaningful, since it alone catches an interval column that disagrees with the actual cadence.
`backfill` now returns its reports rather than only logging them — M1-T4's allowlist and the M9
caveats both need them. 11/11 mutations caught afterwards; suite 97 offline + 3 network.

### M1-T1 complete — trades downloader

`ingestion/fetch_trades.py` + `binance_archive.py` (URL construction, shared with the remaining M1
fetchers). 22 tests: 21 offline against a 200-row real-archive fixture, 1 `network`. Suite now 54
offline + 2 network, all green.

**The spec's predicted bug happened — through an unpredicted mechanism.** The spec flagged the
aggressor-side mapping as "the single easiest thing to get backwards, with no loud failure mode".
It did go wrong on first write, but not by inverting the condition: the CSV is read with
`dtype=str` to preserve precision, so `is_buyer_maker` arrives as the *strings* `"true"`/`"false"`,
and `bool("false")` is `True`. `.astype(bool)` therefore labelled **every trade a sell**, uniformly
and silently. `test_real_fixture_has_both_sides` caught it on the very first run.

Worth recording as a general lesson: the spec was right that the area needed a dedicated test, and
wrong about how it would break. Predicting *where* risk lives is useful even when predicting *how*
it manifests is not.

Two behaviours chosen deliberately: `date` is derived per-trade from the timestamp (so monthly
archives split into correct daily partitions), and `backfill` refuses to skip a missing month
unless `allow_missing` is passed — a 404 before a symbol's listing date is explainable, but
explainable gaps must be acknowledged rather than absorbed. Skipped months are returned for M1-T4's
allowlist.

Verified by mutation: **7/7 injected defects detected**, each by exactly one named test. The
`network` test confirms the exact klines reconciliation against the live archive.

**The pre-push review then found six more things, one serious.** Tests were not isolated from the
real data root, and `cached_fetch` writes into `data/.cache/` under the *archive's own filename* —
so a test's synthetic payload had left a 199-row punched fixture sitting in
`data/.cache/0GUSDT-trades-2026-08.zip`. A later real backfill would have reused it as genuine
archive data. Fixed structurally: an autouse `conftest.py` fixture repoints `PERPCARRY_DATA_ROOT`
per test, with tests asserting the cache stays inside it (C9 updated).

Second substantive finding: `backfill` never checked `trade_id` continuity **across** month
boundaries, though the criterion says "within and across days" — a wholly missing file between two
intact months would leave both looking perfect. Also fixed: duplicates reported as "gaps" despite a
different cause, `klines_volume` skipping the checksum verification every other download performs,
and a docstring claiming exactness it did not provide.

Then mutation testing found **three of those fixes were themselves untested** and passed with the
fix deleted. Now caught, and recorded in C12: code written in response to a review is at least as
likely to be under-tested as code written the first time.

Asking what the suite still did *not* cover then found two more: **`backfill` could store nothing
at all** and every test passed (all coverage was of refusal paths, none of the happy path), and a
monthly archive whose rows spill into the next month **silently loses them** to
`delete_matching` — two rows in, one row gone, demonstrated. Both now guarded and mutation-checked.

Final state: 64 offline + 2 network tests green, `data/` empty after a full run, and 7/7 mutations
on `fetch_trades.py` caught.

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
