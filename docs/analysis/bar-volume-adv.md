# BTC/SOL bar-derived ADV admission

2026-10-11 UTC. The existing futures one-minute archives cover every day from
2025-06-01 through 2026-09-30: **487 days and 701,280 minutes per symbol**.
All 16 monthly ZIPs per symbol were rehashed against their ingestion reports'
recorded published checksums, source identities were bound, and complete ordered
minute grids/close times were revalidated. Original decimal base and quote volumes
were summed without passing through the converted float64 columns.

This supports **457 strictly prior 30-completed-day ADV windows per symbol**, from
2025-07-01 through 2026-09-30, including all 365 study days. The current UTC day is
always excluded. The causal feature hash covers the method, symbol, window and
prior date/base-volume/source-URL rows. Whole-month archive/report hashes live in
separate offline provenance, so later-month checksum changes cannot change an
earlier feature when its prior values are unchanged.

Daily base-volume ranges are 25,131.185–670,089.741 BTC and
4,518,719.07–85,387,648.91 SOL. September's ADV at the first study decision is
107,578.571 BTC and 25,109,380.017333… SOL. These are denominators, not capacity
or strategy results; Decimal division uses a fixed 60-digit context.

Exact new bar sums match the recorded exact trade totals on all four existing
pilot days per symbol (June 1, July 1, October 1, 2025; September 1, 2026).
This comparison uses hashed prior trade reconciliation reports, rather than a
fresh raw-trade replay. October 10, 2025 remains rejected as raw-trade evidence:

| Symbol | Bar volume | Rejected trade volume | Missing from trade archive |
|---|---:|---:|---:|
| BTCUSDT | 391,963.632 | 366,126.646 | 25,836.986 BTC |
| SOLUSDT | 62,336,461.14 | 58,130,131.53 | 4,206,329.61 SOL |

The bar alternative supplies a complete, reproducible denominator. Sparse trade
cross-checks do not prove every archive total is correct, and source completeness
does not clear book replay, funding marks, fees, contract regimes or model adequacy.
Historical archive admission also does not prove publication latency at midnight.

## Explicit use

Raw-trade ADV remains the default. M5 calibration opts in with
`--adv-source futures_bars` and records both the causal ADV feature and offline
archive provenance. `verified_inputs` regenerates that evidence during downstream
fit admission; changed evidence is rejected. It retains independent full-day book
replay, partition freshness and corpus book-quality gates. It drops unused same-day
and prior raw-trade requirements only for this explicit bar method.

M7 can populate its existing sizing inputs from
`bar_volume.verified_average_daily_volume(root, symbol, as_of)` during offline
manifest preparation. Convert `base_adv` directly to Decimal; copy the UTC window
bounds and causal evidence hash. No M7 research manifest has yet been assembled.

Regenerate offline audits with:

```bash
uv run python -m perpcarry.tools.audit_bar_volume --root data/btc-sol \
  --symbol BTCUSDT --output data/btc-sol/reports/bar-volume-BTCUSDT.json
```

The tool refuses to overwrite its output. Substitute SOLUSDT for SOL; choose a
new output path when an audit already exists. Local daily audits and derived
windows live under `data/btc-sol/reports/bar-volume-{symbol}.json` and
`bar-adv-windows-{symbol}.json`; these dense artifacts are gitignored.

Verification: 42 scoped Python checks passed. All 16 injected defects in a scratch
copy caused named failures, including exact decimal precision, current-day leakage,
future-dependent hashes, stale source evidence and downstream M5 admission. No
book download was interrupted and no raw-trade backfill was performed.
