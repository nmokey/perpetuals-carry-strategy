# M1 mark-price archive acquisition

Status: implemented and acquired, 2026-10-10; specification preceded implementation.
Task scope is BTC/SOL mark bars,
not a funding-payment methodology change or an M8 run.

Acquire the 30 Binance USD-M monthly `markPriceKlines` 1-minute archives for
BTCUSDT/SOLUSDT, July 2025 through September 2026 inclusive. Stream downloads through
existing checksum/cache helpers; require published SHA-256. Use a dataset-specific cache
because mark and trade kline archive basenames are identical. Normalize one month at a
time to Hive symbol/date Parquet under the isolated BTC/SOL root. Preserve original
OHLC decimal strings. Record source URL, checksum, output hashes, complete calendar and
UTC endpoints in a separate provenance report.

Reject missing, duplicate, shuffled or wrong-month minutes, wrong close times,
nonpositive/nonfinite OHLC and inconsistent extrema. Accept only the exact archive
header or no header, never silently discard a malformed first data row. A full bar is
available at `close_time + 1` milliseconds; its close/high/low must not be exposed at
open time. Retain open time separately. No extrapolation, forward fill or sorting to
hide missing rows. Reruns verify cached bytes and regenerate deterministic partitions.

These are mark-price *bars*. Their opens are candidate settlement proxies, not proof
of the exact mark used by the venue at funding time. Exact funding marks remain gated:
the official funding-history response has an associated `markPrice`, but venue API
access is unavailable on this host. Do not call blocked venue APIs. Alternatives are
an authorized accessible host/export or explicitly documented proxy sensitivities;
neither is silently adopted by this acquisition.

Acceptance: offline synthetic tests detect each structural violation, checksum omission
and cache collision; genuine downloads pass calendar checks, all 30 sources/checksums
and generated hashes are recorded locally. Inject faults in an isolated scratch copy
and confirm named tests fail. No raw vendor rows enter git or CI; no book-worker edits.

Source defect found during acquisition: June 2026's BTC and SOL monthly archives omit June 29.
An explicitly recorded repair may combine a checksum-verified daily archive for each
entire missing day with the monthly rows, then run the same complete-month checks.
Repair only monotonic, unique, aligned, in-month monthly rows with whole missing days;
never repair duplicates, malformed times or isolated missing minutes. Each daily input
must itself have its exact UTC minute calendar. Record original monthly row count and
all supplemental URLs/checksums separately. This is archive reconciliation, not filling.
