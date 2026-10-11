# M1-T6 — Research spot/futures price bars

**Status:** Implemented 2026-10-08; complete June 2025–September 2026 spot/perp research
acquisition verified (487 days per market/symbol). See [current status](../../current-status.md).

BTC/SOL carry valuation needs aligned spot and USD-M futures prices across June 2025–September 2026. Download public 1m monthly archives with mandatory published SHA-256 checksums. Separate identically named spot/futures archive caches and market partitions. Normalize January 2025 onward spot microseconds to milliseconds, leaving futures milliseconds intact.

Admission requires an exact ordered minute grid for the month, valid close timestamps, finite positive OHLC, consistent high/low bounds and nonnegative volumes/trade counts. Mark each close available only at the next minute boundary. Persist source checksum and output fingerprints. No fabricated fill or mark/index price is inferred by ingestion.

`tests/ingestion/test_fetch_price_bars.py` verifies timestamp equivalence, availability, gaps/duplicates/order, bad values, and cache/storage isolation. A minute-grid failure blocks that archive rather than being interpolated. This extension supplies valuation data; it does not itself establish admitted settlement marks, execution prices or research
accounting policy. M7 accounting engineering is now implemented separately.
