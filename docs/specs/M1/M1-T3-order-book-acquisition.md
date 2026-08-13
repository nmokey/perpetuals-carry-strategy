# M1-T3 — Order book historical data acquisition

**Milestone:** M1
**Status:** **Blocked — OD-2 unresolved.** Per convention C4 this spec is not written around an
assumed resolution. What follows is the evidence needed to *make* the decision, and what the spec
becomes under each option.
**Depends on:** M0-T4 (complete), **OD-2 resolved** (open), OD-1 (open)
**Design doc:** Section 3.2, Section 4.1, OD-2, Risk R1

## Goal

Acquire order book data sufficient to reconstruct book state at arbitrary timestamps, so the M4
impact simulator can walk it. This is the project's highest-risk dependency: the entire
contribution is that execution costs are *calibrated from real book data*, so the fidelity
available here bounds what the project can honestly claim.

## Findings — verified 2026-08-12

The design doc's OD-2 option (c), "approximate using top-of-book / partial-depth snapshots (free,
immediately available)", **does not exist in the form assumed.** Both free Binance candidates were
downloaded and inspected:

### `bookDepth` — not an order book

Sampled `BTCUSDT-bookDepth-2026-06-01.zip` (current, actively maintained):

```
timestamp,percentage,depth,notional
2026-06-01 00:00:07,-5.00,9474.17100000,683676749.44930000
2026-06-01 00:00:07,-0.20,354.43700000,26073796.28200000
```

- **Not price levels.** It is cumulative depth at 12 fixed percentage distances from mid:
  ±0.2, ±1, ±2, ±3, ±4, ±5%.
- **~2,628 samples/day**, irregularly spaced (~30s), timestamps to the second only.
- No `update_id`, no diffs, no per-level prices or quantities.

This cannot drive a book walk, and cannot exercise the M2 `OrderBook` / `BookReplayer` design
(price-level add/modify/delete, snapshot + sequenced diffs) at all — it is a different data model.

It is not useless: cumulative notional within ±X% of mid is close to a direct read on "how much
can I execute inside X% impact", which is a crude capacity curve. But it cannot produce
size-resolved slippage for orders smaller than the ±0.2% bucket, which is where most of the
interesting range lies.

### `bookTicker` — discontinued

L1 best bid/ask. Available 2023-05-16 through **2024-03-30**; every date from 2024-04-01 onward
returns 404 (probed directly). So free L1 history is frozen two years in the past, and cannot be
extended.

### Live capture from this location is venue-constrained

| Source | Reachable from here | L2 available |
|---|---|---|
| Binance archive (S3) | Yes | **No** — see above |
| Binance REST/WS (`fapi`/`fstream`) | **No** — geo-blocked, `"restricted location"` | n/a |
| Bybit | **No** — CloudFront country block | n/a |
| OKX REST/WS | Yes | **Yes** — `/api/v5/market/books` returns levels with a `seqId` |

OKX's books channel carries `seqId`, which maps cleanly onto Section 3.2's `update_id` and
supports exactly the snapshot + sequenced-diff model the C++ replayer is designed for.

## What this means for OD-2

The options in the design doc need restating against the evidence:

- **(a) Record live depth-diffs.** Still viable, but **not on Binance from this machine** — the
  venue is geo-blocked. On OKX it works today and yields true L2 with sequence numbers. Cost: the
  analysis window starts empty and grows from the day recording begins, so every day of delay is a
  day permanently unavailable.
- **(b) Buy from a vendor** (e.g. Tardis.dev). Unchanged, and the only route to *historical* L2.
  Adds cost, plus licensing constraints that would tighten C9 (never let vendor data reach CI
  caches or artifacts).
- **(c) Free partial-depth approximation.** **Substantially weaker than the design doc assumes.**
  Realistically: `bookDepth` percentage buckets (current, coarse) or `bookTicker` L1 (finer, but
  ending 2024-03). Neither supports a book walk.

**A fourth option, not in the design doc:** run the whole project on **OKX** rather than Binance —
recording L2 live while pulling OKX trades and funding for the same window. Self-consistent venue,
true L2, no geo-blocking. Cost: no deep historical archive, so the analysis window is bounded by
recording time.

**What must not happen:** mixing venues — Binance trades/funding with an OKX book. The impact
model would be calibrated on a different market's liquidity than the funding edge it is netted
against, and the headline capacity number would be meaningless.

## Consequence for M2, if (c) is chosen

M2's `OrderBook` and `BookReplayer` assume price-level state and sequenced diffs. Under (c) there
is nothing to replay, and M2 would need re-scoping — which also removes most of the C++ systems
content the milestone ordering treats as independently demonstrable (Risk R3). This makes OD-2
a decision about the shape of the project, not just a data-sourcing detail.

## Acceptance criteria

Copied verbatim from the design doc Section 5 table:

> Book state reconstructable at any timestamp in the recorded window; validated against a
> known-good reference snapshot

Note this criterion is **unsatisfiable under option (c)** as the data actually exists: percentage
buckets do not constitute reconstructable book state, and there is no independent snapshot to
validate against. Choosing (c) requires rewriting the criterion, not just the implementation.

Under (a)/(b) it expands to:

| # | Test |
|---|---|
| 1 | Replaying diffs from a snapshot reproduces a later independently-captured snapshot, level for level, within a documented depth |
| 2 | A dropped sequence number is detected, not silently absorbed |
| 3 | Recorder gap/downtime is recorded as an explicit gap, never interpolated |
| 4 | Reconstructed best bid/ask at sampled timestamps matches an independent L1 source |

## Open questions

**Q1 — OD-2, restated with evidence: (a) on OKX, (b) purchase, (c) accept a much weaker
approximation, or (d) move the whole project to OKX?** This is the decision. My recommendation:
**start an OKX L2 recorder now, today, regardless of the final choice.** It is cheap, it is the
only option whose cost is *time*, and the data it accumulates is worthless if started late and
valuable if started early. It preserves (a) and (d) while the rest is decided, and can be thrown
away at no loss if (b) is chosen.

**Q2 — if the venue splits, does the project still answer its question?** Related to Q1. Worth
deciding explicitly rather than discovering at M8 that the two legs are incomparable.

**Q3 — does OD-3's altcoin have usable L2 on the chosen venue?** Liquidity ranking drives symbol
choice at M8, but the recorder has to be pointed at symbols *now*. Recording a couple of plausible
altcoin candidates alongside BTC costs little and avoids being unable to run M8-T2 later.

**Q4 — how long a window is enough?** The impact model needs enough size/time variation to fit
(M5-T1) and the backtest needs enough funding cycles to be meaningful (M7-T3). Nobody has stated a
minimum. This should be answered before committing to a recording-based approach, since it sets
the project's critical path.
