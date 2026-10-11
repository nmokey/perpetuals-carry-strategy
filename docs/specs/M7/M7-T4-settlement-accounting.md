# M7-T4 — Fee and funding settlement accounting

**Milestone:** M7
**Status:** Implemented and verified 2026-10-10; research inputs remain gated
**Depends on:** M7-T1/T2 implemented; OD-11 resolved (fee sensitivity with cited assumptions)
**Design doc:** Section 5, M7

## Goal and acceptance
Provide the pure accounting contract for T3: actual executed quantities/prices, explicit
dated taker fee schedules, funding on current short exposure at the settlement mark,
and gross/net equity reconciliation.

> P&L reconciles against a hand-computed example trade

Tests pin cash, inventory, derivative realized/unrealized P&L, positive/negative funding,
fees on each fill, partial exits, unequal hedge legs, changing marks, and gross/net costs
against independently computed examples. Reject malformed, duplicate, backwards,
out-of-scope and missing-settlement events without changing the immutable ledger.

## Design and interfaces
`FeePeriod` specifies symbol, market, half-open effective dates, taker fraction, source,
source observation date and evidence kind. `FeeSchedule.quote` rejects gaps, overlap and
unapproved assumptions. The committed reference table is explicitly an assumption for
the study, not evidence of historically verified rates; normal admission defaults off.
Fee sweeps use caller-supplied schedules, never a hidden fallback.

`Ledger.start(symbol, initial_capital_usdt, next_funding_ms, fees)` creates a frozen
ledger. `fill(Fill)` and `settle(FundingSettlement)` return new ledgers; `value(Marks)`
returns cash, exposures, price P&L, funding, fees, execution costs and gross/net equity.
Prices, quantities and cash use Decimal; no compiled replay import or ingestion I/O.

Spot buys consume cash; opening a short derivative does not generate sale proceeds.
Each leg can partially fill/close independently; no implicit perfect hedge. Funding cash
is minus signed perp quantity times the actual settlement mark times the rate. Charge
fees on actual executed notional, once. Spread/impact already in fill prices are not
deducted again. Signed execution cost is quantity change times (fill minus reference
mid); gross uses the same executed quantities at those reference mids, with the same
funding marks, excluding fees and explicitly supplied financing costs.

Funding timestamps are nominal UTC boundaries. Settlement rows carry their actual
interval and a contemporaneous mark; archive timestamp jitter must be normalized and
validated by T3 before calling this API. A required next-settlement cursor prevents
skipping settlements even when flat. The interval determines the next boundary; a
future announced cadence change requires caller calendar handling, not future rate use.
T3 must start at the study's initial relevant boundary and consume its flat settlement
before entering. Without a consumed boundary the ledger has no previous-boundary timing
information; it does not infer that an earlier settlement never occurred.
Binance documents possible 15-second settlement timing deviation: reject perp fills
within 15 seconds on either side of a nominal settlement, instead of inventing exact
eligibility. Funding itself has no trading commission.

## Explicit approximations and research gates
Fees are USDT quote-equivalent deductions: spot base-asset commission, BNB discounts,
rebates and fee-token inventory are not simulated. This is economic cost accounting,
not a venue wallet replica; OD-4 remains open. Cash may be negative; the ledger reports
it rather than inventing financing or liquidation. Margin reservation, maintenance,
liquidation and capital admission belong to T3/research policy and remain B-010 gates.
The caller supplies independently admitted, contemporaneous spot/perp valuation marks
and actual funding marks; trade-price klines cannot silently replace funding marks.

## Sources and fee provenance (checked 2026-10-10)
- [Binance funding rules](https://www.binance.com/en/support/faq/detail/360033525031):
  signed transfers, mark-valued exposure, settlement eligibility and timing uncertainty.
- [Binance fee calculation](https://www.binance.com/en/support/faq/detail/360033544231):
  executed-notional commission; its 0.05% taker illustration is hypothetical.
- [Binance spot fee table](https://www.binance.com/en/fee/trading): current regular-user
  0.10% rate, without a historical effective-date archive.

Thus the reference scenario uses 0.05% perp / 0.10% spot, with no discount, expressly
unverified for July 2025–September 2026. Historical base-case admission remains open;
do not mark OD-11's research evidence complete because a table now exists.

## Invariants and scope
No future rate/mark lookup, estimated-cost subtraction, implicit fee fallback or assumed
financing accrual, short spot, long perp, position reversal, or capacity/Sharpe claims.
Fill records do not certify sizing, liquidity or capital admission; T3 must obtain those
from T2/execution and the declared capital policy before accounting.
Unique event identifiers and chronological boundaries make accidental replay fail.
T3 owns ingestion adapters, execution and walk-forward causality; M8 owns metrics and
fee sensitivity runs. C12 mutation checks must exercise monetary and admission faults.

## Hand reconciliation
Synthetic example: start with 10,000 USDT; buy 2 spot at 101 and short 2 perp at 99,
both against mid 100. Reference fees are 0.10% spot / 0.05% perp. Receive funding
2 × 110 × 0.001 = 0.220, then mark spot/perp at 110/112. Exit spot at 109 (mid 110)
and perp at 113 (mid 112), and pay explicit financing 0.5 USDT.

| Checkpoint | Cash | Actual price P&L | Gross P&L | Net P&L |
|---|---:|---:|---:|---:|
| Entry, marks 100/100 | 9,797.699 | -4 | 0 | -4.301 |
| Funding, marks 110/112 | 9,797.919 | -8 | -3.780 | -8.081 |
| Flat after exits and financing | 9,987.088 | -12 | -3.780 | -12.912 |

Final trading fees = 0.632, execution cost = 8, financing = 0.5.
Net = -3.780 - 8 - 0.632 - 0.5 = -12.912 USDT. The funding mark is deliberately
different from entry and valuation prices, and exits have different notionals, so
entry-notional funding or charging one fixed fee cannot accidentally pass this example.

Arithmetic uses a fresh 50-digit Decimal context, independent of ambient precision and
rounding. It does not simulate exchange commission quantization. Verification includes
the full offline suite, compiled-free imports and isolated C12 faults; see `progress.md`
for the actual counts and checks. No real BTC/SOL strategy result is inferred.
