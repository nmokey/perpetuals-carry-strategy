# M5-T3 — Model serialization

**Milestone:** M5
**Status:** Implemented 2026-10-09; synthetic verification complete, BTC/SOL exports data-gated
**Depends on:** M5-T2
**Design doc:** Section 4.5, Section 5 (M5)

## Goal

Save the fitted impact model to JSON and load it back. Small task, and the reason it exists is
reproducibility: M7's backtest must consume a *fixed, inspectable* set of coefficients rather than
re-fitting on every run, or the strategy's behaviour changes silently whenever the calibration data
does.

## Acceptance criteria

Copied verbatim from the design doc Section 5 table:

> Loader round-trips saved params without loss

Expanded into checkable tests:

| # | Test | Where |
|---|---|---|
| 1 | Save then load returns coefficients that are **bit-identical**, not merely close | `tests/models/test_impact_model_io.py` |
| 2 | The round-trip survives values that a naive `%.6f` would damage — a coefficient needing 17 significant digits | same |
| 3 | The saved file records provenance: symbols, corpus days, row counts, fit date, and the code version that produced it | same |
| 4 | Loading a file whose schema version is unknown fails loudly rather than silently ignoring fields | same |
| 5 | The caveat fields survive the round trip: which regime each coefficient covers, and how many of its rows were beyond validated depth (D-021) | same |
| 6 | A file missing a required field is rejected; a file with an unexpected extra field is rejected too, so a renamed field cannot read as a default | same |

Test 2 is the M2-T3 lesson applied here: a number written for human readability rather than
round-trip is a number that changes when it is saved. An impact coefficient that shifts in the
sixth decimal is a different capacity answer.

Test 5 is what stops the serialized model from becoming the place the caveats get lost. A JSON file
of three coefficients is exactly the artifact someone downstream will treat as authoritative and
context-free.

## Design

**JSON, and human-readable on purpose.** This file gets read in review, quoted in the M9 writeup,
and diffed when the calibration is regenerated. It is small, it is not on any hot path, and a binary
format would buy nothing.

**Floats are written with `repr`/shortest round-trip**, exactly as M2-T3's `format_price` does and
for the same reason: `json.dump` already does this in Python, so the requirement is to *not*
override it with formatting for prettiness.

**A schema version field, checked on load.** The model will gain fields — a spread term, per-regime
coefficients, a sliced-execution variant. A loader that silently tolerates unknown shapes is one
that will one day load a v1 file into v2 code and produce plausible numbers.

**Provenance is part of the model, not metadata about it.** Which days it was fitted on bounds what
it can be applied to, and with book coverage at ~12 days per symbol per year that boundary is tight
enough to matter.

## Data

- **In:** the fit object from M5-T2.
- **Out:** `models/impact_<symbol>.json` — committed, because coefficients and capacity curves are
  explicitly publishable where raw book rows are not.

## Invariants this task must not break

**Determinism / reproducibility.** The whole point: a saved model makes M7's backtest reproducible
independently of whether the calibration corpus is present.

**Honest limitations.** Test 5. The caveats travel with the coefficients or they are lost at exactly
the handoff where someone stops thinking about them.

## Out of scope

- Fitting — **M5-T2**.
- Consuming the model in a strategy — **M7**.
- Versioning or migrating old model files. There is one version; write the check that will make a
  second version safe, not the migration for a version that does not exist.

## Open questions

**Q1 — commit the fitted model file, or regenerate it?**
Recommendation: commit it. It is small, publishable, and it is what makes an M7 backtest
reproducible on a machine with no corpus. Regenerating on demand would tie every backtest to the
presence of licensed data.

**Q2 — one file per symbol, or one file with all symbols?**
Recommendation: one per symbol. Symbols are fitted independently, arrive at different times, and
M8's comparison reads them side by side; a single file would make a re-fit of one symbol touch
every symbol's provenance.

## Implemented contract (2026-10-09)

`python/perpcarry/models/impact_model_io.py` provides `from_fit_report`, `save`, `load`,
and explicit `law` lookup. Schema 1 stores evaluated laws per symbol, side, schedule,
depth and training-only size regime. Square-root remains primary; linear and power
diagnostics retain their identity. No best-score selection or missing-stratum fallback
occurs. Negative coefficients and their unusable flags survive serialization.

Provenance includes the exclusive chronological boundaries, supporting corpus days,
fit date, Git revision plus working-tree fitting-source SHA-256, and calibration
manifest hashes. Row totals count only all-size square-root strata once; bins and
diagnostic forms overlap and must not be summed as unique events. Each fit records
train/test counts, dates, size bounds and edges, signed-target counts and beyond-depth
row counts. Coverage/exclusion caveats and unsupported strata travel with the laws.
Dense residuals, raw prices/book levels and report plots stay outside the artifact.

Every structured object rejects missing/extra fields. Unknown versions, duplicate
JSON keys/fit identities, nonfinite values, inconsistent units/exponents/counts and
days crossing the split fail validation. Verified exports require manifest evidence
for every supporting corpus day; synthetic provenance must be explicitly selected.
Writes validate before atomically replacing a file and use standard shortest-round-trip
JSON float encoding. Loading needs neither the calibration corpus nor a refit.

The fitting CLI accepts `--model-dir models/<fold>` to export one file per symbol
after admission/fitting. Use a separate directory per fold to retain fixed historical
models. Only real admitted coefficients are candidates for committing; no BTC/SOL
artifact is fabricated while the calibration corpus remains unavailable. This task
implements serialization, not validation of annual capacity or strategy performance.
