# M1: Explicit futures-bar volume alternative for ADV

Status: implemented and locally verified (2026-10-11 UTC).

Use already acquired Binance USD-M one-minute trade-price bars as an explicitly
labeled alternative to D-022 raw-trade ADV. Preserve the raw-trade default and
rejected trade archives. Spot volume is not perpetual ADV.

Verify cached monthly ZIPs against published checksums recorded by price ingestion;
bind reports to requested symbol, futures market, month and source URL. Require
complete ordered minute grids and valid close times. Sum original decimal text,
not float64 converted volume. Require finite nonnegative volumes and positive days.

The artifact records daily base/quote volume, counts and archive/report fingerprints.
ADV averages precisely the 30 completed UTC days before a decision's UTC day,
excluding its current day. Decimal operations use an explicit 60-digit context.
The causal feature hashes only prior dates/base volumes/stable source URLs; offline
whole-month archive/report fingerprints are retained separately in admission evidence.
These archives are provenance, not historical publication-time evidence. Corpus
admission checks all source rows before a chronological study; it is separate from
feature construction over already admitted daily values.

Test exact sums, source/checksum binding, missing minutes/days, strict prior windows,
and future poisoning/withholding. Inject implementation defects in a scratch copy.
Compare four existing pilot days per symbol with hashed reconciliation reports and
retain rejected October 10 trade discrepancies. Sparse checks cannot prove all
archive totals correct. Dense artifacts belong in gitignored data reports.

M5 may opt in explicitly, retain independent book and corpus admission, and record
ADV method and window fingerprint. M7 can consume the feature's value and fingerprint
through existing dated sizing inputs. No raw trades are re-admitted by this path.

Verified: 42 scoped tests pass; all 16 scratch-injected defects produce named test
failures. Both symbols have 487 checksum-verified complete UTC days, supporting all
457 warmup/study daily windows. See `docs/analysis/bar-volume-adv.md` for evidence
and limits. Independent book replay and actual BTC/SOL calibration remain pending.
