# Code organization audit — 2026-10-09

Historical audit of organization before M6 implementation. Subsequent M6/M7 work is
complete; use [current status](current-status.md) for the active milestone and gates.

The existing C++ core has clear ownership and I/O boundaries. The main maintainability
problem was in the newer Python code: reusable calibration depended on command-line
tools and their private helpers. That dependency direction is now corrected, with
regression checks covering the moved behavior. M6 was unimplemented at the time of this audit.

## Findings and changes

| Finding | Why it mattered | Resolution |
|---|---|---|
| Calibration imported private book readers and row conversion from `tools/export_book.py` and `tools/run_pipeline.py` | A CLI implementation change could break research code; core routines were hard to find | Book discovery/schema live in `ingestion/book_partitions.py`, ordered streaming in `storage.py`, and the C++ batch adapter in `replay.py` |
| Models imported partition hashing from `tools/corpus_inventory.py`, which imported calibration back inside a function | Introduced a dependency cycle and obscured the actual shared API | File/partition content hashing lives in dependency-light `integrity.py`; the inventory tool can use normal imports |
| Funding and price ingestion imported calendar utilities from other fetchers | Unrelated dataset modules were coupled through general date arithmetic | Shared UTC helpers live in `ingestion/calendar.py`; legacy public fetcher imports remain available |
| Statistical fitting and model loading imported the C++ calibration generator at module load | Reading fixed coefficients unnecessarily required compiled replay | The generator is imported only when admitting calibration; a fresh-process test blocks the extension and verifies statistical imports still work |
| Schema validation used one large function with abbreviated local names | Coverage and consistency rules were difficult to scan independently | Separate provenance, per-fit and whole-artifact validators; explicit local names; schema and numerical behavior retained |
| Adapter tests lived under CLI tool tests | Test locations reinforced the old ownership | Adapter tests moved to `tests/test_replay.py`; tool tests retain checkpoint/report responsibilities |
| The existing ordering test used one fragment | Reversing fragment order was not detected despite the test's name | Added a multi-fragment test with tied timestamps that pins supplied file order and exact values |
| Current guidance still named M5-T3 as next and OD-8 as unresolved | Future work could follow stale instructions | Updated current milestone status, Bayesian decision guidance and the dependency map |

Existing command names, data paths, report formats, schema version, coefficients and
research scope are preserved. `download.sha256`, fetcher calendar helpers and the
inventory fingerprint helper retain their public imports. Export/pipeline error names
remain importable aliases to errors owned by the library. Research code no longer
depends on private CLI functions.

## Dependency map

- `integrity.py`: content hashes; standard library only.
- `storage.py`: Parquet storage and ordered fragment streaming.
- `ingestion/`: archive schemas, date ranges, download/normalization, partition discovery,
  metadata and corpus validation.
- `replay.py`: Arrow-to-C++ batch conversion; preserves row order and rejects unknown sides.
- `models/`: order normalization, calibration, statistical fits and fixed model artifacts.
- `tools/`: command-line orchestration, corpus reports, probes and developer diagnostics.
- `cpp/`: deterministic book/replay/execution logic, the SPSC boundary, bindings and
  separate file-I/O tools.

`tests/test_architecture.py` rejects library imports from `perpcarry.tools` and verifies
statistical model imports without the compiled replay extension. These checks run in
the existing offline CI tier.

## Remaining maintenance work

These are follow-ups, not observed failures of the current cleanup:

- `ingestion/validate_data.py` remains about 1,000 lines. Its registered checks already
  have explicit boundaries and extensive acceptance tests. If checks grow, split result/
  corpus types and check implementations behind the current public API, preserving
  registration order and quality-report semantics.
- `models/impact_model.py` still owns fitting, admission, plots and a CLI in one module.
  The dependencies are corrected, but future plotting/command additions should move into
  reporting/tool modules rather than enlarging the fit loop. Keep chronological fitting
  and training-only size regimes covered when splitting it.
- Newer server commands such as `assess_study`, `validate_book`, `benchmark_trades` and
  `investigate_trades` have less direct orchestration coverage than their underlying
  ingestion/admission routines. Add mocked command tests when changing those commands;
  their local execution is not evidence that CI covers all subprocess/report branches.
- Configuration/provenance and replay-summary tools still assume a source checkout.
  For example, `assess_study` loads a checkout-relative TOML at import time and includes
  a dated regular-day URL probe. Generalize configuration loading and date construction
  if supporting arbitrary study configs or installed-wheel operation becomes a task.
- Some C++ bindings and historical comments could receive a dedicated formatting pass.
  This audit found no organization reason to rewrite ownership, queue or simulator code.

## Verification

- 428 offline Python tests passed; 10 network tests deselected.
- 85 existing C++ tests passed; this cleanup changed no C++ source.
- Ruff lint/format and `git diff --check` passed.
- Six scratch-only mutations detected: reversed fragment order, swapped price mapping,
  broken content hash, wrong month anchor, backward CLI dependency and a compiled-replay
  dependency added to statistical imports.
- All nine M5-T3 serialization mutations were rechecked after validator decomposition:
  precision loss, unknown versions, extra fields, depth counts, chronological leakage,
  missing evidence, duplicate keys, caveat loss and signed-cost clipping were detected.

Mutation output stays under ignored `data/reports/cleanup-mutation-audit.json` and
`data/reports/m5-t3-mutation-audit.json`. No downloads, model fitting, dependency changes,
commits or remote writes were part of this cleanup. Real BTC/SOL calibration remains
data-gated; engineering cleanliness does not establish capacity or Sharpe.
