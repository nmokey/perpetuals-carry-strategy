# Blockers

Anything preventing a milestone task from starting or finishing, plus known defects in the design
doc that will cause trouble when their milestone comes up.

Each entry: what is blocked, what would unblock it, and whether there is a usable interim path.
Move entries to **Resolved** with a date rather than deleting them — the resolution is often the
more useful record.

---

## Active

### B-001 — OD-2: historical L2 order book data is not secured

**Blocks.** M1-T3, and therefore M2's validation-against-real-data criteria and everything
downstream. This is the project's highest-risk dependency.

**Situation.** Trades and funding rates are freely archived; full L2 depth history generally is
not. Options are (a) record live websocket depth-diffs for weeks, (b) buy a range from a tick-data
vendor, (c) approximate with free partial-depth snapshots.

**Interim path.** The design doc's recommendation — start with (c), run (a) in parallel — **does
not survive contact with the data**: see B-005 for why (c) does not exist as described, and B-004
for why (a) cannot be run against Binance from this location. Neither has been started.

**Unblocked by.** A decision on OD-2 made against the evidence in B-004/B-005 and
`specs/M1/M1-T3-order-book-acquisition.md`, plus — if any recording-based option — actually
starting the recorder, since every day of delay is a day of lost data.

---

### B-004 — Binance's REST/WS API is geo-blocked from this location; Bybit too

**Blocks.** Any live capture or REST pull from Binance — most importantly M1-T3 option (a).
Does **not** block M1-T1 or M1-T2.

**Verified 2026-08-12.** `fapi.binance.com` returns `"Service unavailable from a restricted
location according to 'b. Eligibility'"` for `/fapi/v1/fundingRate` and `/fapi/v1/depth`. Bybit's
`api.bybit.com` returns a CloudFront country block. **OKX works** — `/api/v5/market/books` returns
L2 levels with a `seqId`, and its funding history endpoint responds normally.

`data.binance.vision` is S3-backed and **not** geo-blocked, so the historical archives (trades,
aggTrades, klines, fundingRate, bookDepth) remain fully available. The split matters: Binance is
the better source for *history* and an unavailable source for *live capture*, from this machine.

**Unblocked by.** Choosing a venue for live capture (OKX is the working option), or accepting
that live capture happens elsewhere. Note that using a VPN to reach a venue that has deliberately
geo-blocked the user is a terms-of-service question, not just a technical workaround.

---

### B-005 — OD-2 option (c) does not exist in the form the design doc assumes

**Blocks.** M1-T3, and it changes the *shape* of the OD-2 decision rather than just its cost.

**Verified 2026-08-12** by downloading and inspecting the actual files. See
`specs/M1/M1-T3-order-book-acquisition.md` for the evidence in full.

- `bookDepth` is **not** an order book: cumulative depth at 12 fixed percentage bands (±0.2, ±1..5%)
  from mid, sampled ~2,628×/day at irregular ~30s intervals, no `update_id`, no per-level prices.
  It cannot drive a book walk and cannot exercise the M2 replayer design at all.
- `bookTicker` (L1) **was discontinued**: available 2023-05-16 → 2024-03-30, 404 from 2024-04-01.

So "free partial-depth snapshots, immediately available" is really "coarse percentage buckets, or
two-year-stale L1". The design doc's recommended interim path — start with (c) to unblock M2 —
does not work, because there is nothing for M2 to replay.

**Consequence.** M1-T3's acceptance criterion ("book state reconstructable at any timestamp,
validated against a reference snapshot") is **unsatisfiable under (c)**. Choosing (c) means
rewriting that criterion and re-scoping M2, which removes most of the C++ systems content the
milestone ordering treats as independently demonstrable (R3).

**Unblocked by.** An OD-2 decision made against this evidence. A fourth option not in the design
doc — run the whole project on OKX, recording true L2 live — is now the most direct path to the
stated criterion. Recommendation: **start an OKX recorder now regardless**, since it is the only
option whose cost is measured in elapsed time, and it is discardable at no loss.

---

### B-002 — No C++-side Parquet reader is specified

**Blocks.** M2-T2 / M3, whichever first needs the C++ core to consume stored data.

**Situation.** The Section 2 architecture diagram shows Python writing Parquet and the C++ core
reading it, but the Section 10 tech stack lists no Arrow C++ / Parquet dependency. The gap is
silent — nothing fails until someone tries to implement the read.

**Options.** Add Arrow C++ as a dependency, or have Python read the Parquet and feed the replayer
across the pybind11 boundary. The latter fits the pipeline-level-boundary rule (Risk R4) and adds
no C++ dependency.

**Unblocked by.** Choosing one and recording it as a D-entry.

---

### B-003 — Book schema assumes diffs that the recommended interim data source lacks

**Blocks.** M1-T3 schema design, M2-T2 replay logic.

**Situation.** Section 3.2 models the book as diffs carrying `update_id` sequence numbers, used
for dropped-message detection. That only exists under OD-2 options (a)/(b). The *recommended*
interim option (c), partial-depth snapshots, has no diff stream and no sequence numbers — so the
documented schema does not describe the data the project plans to start with.

**Unblocked by.** A snapshot-shaped schema alongside the diff schema, and a `BookReplayer` mode
that ingests snapshots directly rather than replaying diffs onto them. Coupled to B-001.

---

## Watch list

Not blocking yet; will bite at the milestone named.

- **M2-T1 / M4-T2 dependency edges are tighter than necessary.** M2-T1 (a pure data structure)
  is listed as depending on M1-T4 (full data QA), and M4-T2 on M3-T2 (the SPSC queue). Both can
  be developed and unit-tested against synthetic fixtures first; the dependency is real only for
  the validate-against-real-data half of each acceptance criterion. Don't let the doc's edge
  serialize work that could proceed in parallel.

- **M7-T4 is sequenced after M7-T3, but T3 needs it.** The backtest loop's P&L requires fee and
  funding settlement accounting. Expect to build a minimal settlement model inside T3 and refine
  it in T4, rather than treating T4 as purely additive.

- **M1-T1's "no gaps in `trade_id`" is venue-specific.** On Binance `aggTrades` the IDs are
  aggregated and gaps are expected by design, so the criterion as written would fail on correct
  data. Either validate against the raw trades endpoint or relax the criterion to monotonicity —
  and say which in the spec.

- **ThreadSanitizer is not yet wired into the build.** M3-T2's acceptance criterion requires a
  TSan-clean stress run; there is currently no sanitizer build configuration, and no nightly CI
  tier to run it in (design doc Section 4.9 specifies the tier; it is not built).

- **CI has never actually run.** The workflow was verified by executing each step's exact command
  locally on macOS, but no GitHub Actions run exists yet. The Linux leg in particular is
  unproven — this project has only ever been compiled by AppleClang on arm64, so the first
  ubuntu run may well surface a missing include or a warning difference. Expect to fix something
  on the first push.

- **Network tests at M1 will need marking before they exist.** The ingestion pulls hit live
  exchange endpoints. They must be `@pytest.mark.network` and deselected by default *from the
  first one written*, or CI becomes flaky and a red build stops being believed (C10, R7).

---

## Resolved

*(none yet)*
