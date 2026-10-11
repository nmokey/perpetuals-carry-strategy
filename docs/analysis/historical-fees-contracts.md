# BTC/SOL historical fee and contract evidence

Audit date: 2026-10-10 (America/Los_Angeles; source capture timestamps use UTC).
Scope: Binance BTCUSDT/SOLUSDT USD-M perpetuals and their spot hedges; July 2025
warmup through the September 2026 study end. This is source research, not an admitted
execution-rule or fee schedule. No existing metadata or fee configuration was changed.

## Verified dated notices

| Instrument / field | Published | Announced change, UTC | Evidence and limits |
|---|---|---|---|
| SOLUSDT perpetual price tick | 2024-10-01 05:00 | 2024-10-14 06:30 | 0.001 → 0.01 USDT; predates the study. Existing orders can still match at their original tick. [Official English notice](https://www.binance.com/en/support/announcement/detail/8bfe2e9b86734cd08f3cbcdb82b79f51). |
| SOLUSDT perpetual minimum trade amount | 2025-03-28 15:48 | 2025-04-02 09:30 | 1 → 0.01 SOL, with trading suspended until 09:31. This is a minimum quantity, not independent proof of a quantity step or minimum notional. The notice also mentions tick updates without specifying a numeric replacement tick. [Official English notice](https://www.binance.com/en/support/announcement/detail/62e7f20e3f2d4313ab7b2147f51065c6). |
| BTCUSDT perpetual minimum notional | 2026-04-09 06:14 | Rollout starts 2026-04-14 06:30 | 100 → 50 USDT, completed within approximately four hours; existing orders unaffected. Exact application time is unspecified. [Official English notice](https://www.binance.com/en/support/announcement/detail/10999fd17dc045de801c0c78ab29e6fc). |

These establish particular announced changes, not exhaustive histories. In particular,
the BTC notice does not justify an exact regime boundary at either 06:30 or 10:30.
Use contemporaneous observations to resolve that boundary, or explicitly document a
conservative rule/sensitivity for the rollout. Do not relabel such a choice as exchange
evidence. The before/after values alone do not prove the entire preceding/following study
period had no other changes.

## SOL empirical grid disagreement

The 2024 tick notice changes the interpretation of B-011: the empirical 0.001 grid on
early study days does **not** by itself establish a 2025–2026 tick change. An exact
Decimal modulo check on the original cached daily trade CSV price strings found:

| UTC day | Total executions | Executions off a 0.01 grid | Distinct off-grid prices |
|---|---:|---:|---:|
| 2025-07-01 | 2,245,956 | 28 | 15 |
| 2025-10-01 | 3,097,739 | 41 | 17 |
| 2026-09-01 | 2,086,101 | 0 | 0 |

Only about 0.00125% and 0.00132% of early-day executions are off-grid, yet those rare
prices are enough to force the GCD estimator to 0.001. The announcement's grandfathered
order provision is a plausible explanation, **not a verified cause** of those executions.
Source defects or intervening rule changes have not been excluded. Execution-price
granularity and the tick accepted for new orders are separate properties.

Targeted official-source searches covered subsequent changes through September 2026,
including year-wide and month-specific tick queries. No later numeric SOL perpetual
re-tick was verified. Search absence is not proof of an uninterrupted 0.01 regime:
indexing is incomplete, and the April 2025 minimum-amount notice has ambiguous tick
language. B-011 remains open pending reconciliation; do not overwrite the committed
metadata with either 0.001 or 0.01 on this evidence alone. Other venues' SOL notices,
Binance.US rules and spot tick changes cannot establish Binance USD-M rules.

## Fees remain explicit assumptions

The [official futures fee FAQ](https://www.binance.com/en/support/faq/detail/360033544231)
was last updated 2026-05-01 11:51 UTC. It illustrates a regular-user USD-M taker rate
of 0.05%, but explicitly labels its calculation rates hypothetical. It confirms fees
depend on account tier and describes a conditional BNB discount. This does not
substantiate a fixed historical rate for either research contract throughout the year.

The [spot fee page](https://www.binance.com/en/fee/trading) is a current reference, not a
dated schedule covering every study month. `config/fee-reference.toml` therefore remains
unchanged: 0.0005 perpetual / 0.001 spot taker fractions are sensitivity assumptions,
with explicit opt-in. No historical fee base case was cleared.

Research policy must specify account/VIP tier, BNB/referral/promotional discounts and
the spot fee asset. The present ledger deducts USDT-equivalent commissions; it does
not model spot base-asset deductions, BNB inventory or venue rounding. A base-asset
commission affects the hedge quantity and cannot be settled by changing only a rate.
Spot execution spread/impact assumptions also remain separate from commission fees.

## Small evidence acquisition and admission status

Local, gitignored evidence is under `data/btc-sol/reports/historical-evidence/`:

- `source-manifest.json`: request URLs, UTC timestamps, response codes, byte counts and
  SHA-256 of received bodies. Both BTC/SOL Tardis instrument requests returned HTTP 401
  with a pro/business subscription requirement; those bodies are failure evidence,
  not metadata. Direct Binance documentation/fee requests returned empty HTTP 202
  responses and did not acquire page contents.
- `reviewed-source-facts.json`: structured paraphrases manually checked against official
  English pages through the web tool. This is not a source-page capture or source-page
  hash. Every record remains outside study admission.
- `sol-observed-grid-check.json`: the aggregate counts above, original archive SHA-256,
  source method and UTC observation time. No raw trade/book rows are published here.
- `tardis-metadata-doc.txt`: successfully downloaded metadata API documentation. Its
  [published contract](https://docs.tardis.dev/api/instruments-metadata-api) says only
  tracked contract-multiplier changes are complete; tick/quantity changes are best-effort
  and fees are illustrative. Even successful access would need cross-checking.

**Cleared:** three dated official announcement facts, the reason rare executions can
dominate empirical grid inference, and the observed metadata access restriction.
**Still blocked:** complete dated spot/perpetual quantity and notional filters, accepted
SOL price-tick regimes, BTC rollout timing, historical fee-base-case evidence and explicit
commission/capital policy. Neither B-010 nor B-011 is closed by this audit.

Validation: reviewed the official English notices and FAQ, recomputed grid counts from
three original CSV archives using exact decimal arithmetic, and checked stored evidence
body hashes. This documentation-only task adds no production code or test fixtures.
