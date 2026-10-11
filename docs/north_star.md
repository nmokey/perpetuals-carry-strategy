# North Star

The stable "why" for PerpCarry. Everything else in `docs/` moves; this file should change
only if the project's purpose genuinely changes.

## The question

> For a given perpetual futures market, does the funding-rate carry edge remain positive after
> realistically modeled slippage and fees — and how does that answer change with order size and
> market liquidity?

The active study fixes **BTCUSDT and SOLUSDT** over **2025-10-01 through 2026-09-30**, with
strictly prior warm-up and walk-forward calibration. Its primary impact model is a fitted
square-root law; entry uses rolling Bayesian AR(1) funding persistence. Capacity is reported in
%ADV and USDT notional alongside gross and net-of-cost Sharpe. See `btc-sol-study.md`.

The proposed 0.04% ADV / $210K capacity, 0.8 net Sharpe, 2.1 gross Sharpe and 400M+ processed
events are hypotheses to test, never outcomes to force. Existing `0GUSDT` evidence validates
engineering only and does not establish BTC/SOL strategy performance.

## What makes this project worth doing

The execution cost model is **calibrated from real order book data, not assumed**, and it
**directly determines** the strategy's entry threshold and position sizing. Most projects do one
or the other: a backtester with a flat assumed cost, or an impact model with no strategy attached.
The contribution is the coupling.

## What "done well" looks like

The deliverable is **a capacity answer, not an equity curve**: a specific size (or range) at which
net-of-cost P&L crosses zero, for at least one symbol, with the modeling honestly caveated.

A rigorous *negative* result — "the edge does not survive realistic costs" — fully satisfies this.
It is not a failure mode and must never be engineered around (design doc Risk R2).

## What would invalidate the work

Ranked by how badly each one destroys the result:

1. **Look-ahead leakage.** Any decision informed by data unavailable at that historical instant.
2. **Assumed rather than calibrated costs** in the main path. The flat-cost variant exists only as
   the M8-T4 naive baseline, for contrast.
3. **Non-reproducibility.** A result that cannot be regenerated from a fixed seed is not a result.
4. **Unstated approximations.** Partial-depth books and a frictionless spot leg are acceptable
   simplifications; presenting them as full fidelity is not.

## Explicit non-goals

Not a live trading system. Not a multi-asset portfolio optimizer. Not a production feed handler.
Not a full simulation of the spot leg — the perp execution leg is the novel part (OD-4).

## Stopping points

The milestone order is designed so the project is coherent and presentable if it stops after
**M4** (systems core), **M7** (full research pipeline), or **M9** (polished writeup). Prefer
finishing a milestone over starting the next one.
