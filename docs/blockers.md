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

**Interim path.** Design doc recommends starting with (c) to unblock M2 onward immediately, while
running (a) in parallel to accumulate true L2 for a later higher-fidelity pass. Neither has been
started.

**Unblocked by.** A decision on OD-2, plus — if (a) — actually starting the recorder, since every
day of delay is a day of lost data.

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
  TSan-clean stress run; there is currently no sanitizer build configuration.

---

## Resolved

*(none yet)*
