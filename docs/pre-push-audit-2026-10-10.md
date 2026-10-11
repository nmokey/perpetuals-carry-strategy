# Accumulated changes audit — 2026-10-10

Reviewed the server work since `45d8ff2`: BTC/SOL study scope and acquisition/validation
helpers, shared replay/storage organization, M5 calibration/fitting/serialization, M6
funding diagnostics/rolling forecasts, and M7-T1/T2 decisions/sizing. User explicitly
requested the audit followed by a push; no additional approval is required by C1.

No blocking implementation defect was found in the reviewed causal, numerical and
admission paths. Corrected stale current-state guidance in `CLAUDE.md`: T3 depends on
T4 accounting and research runs require the existing data/model gates. Earlier dated
progress and audit entries retain their historical verification counts.

## Review focus

- Calibration takes copied consumer replay state after the SPSC queue; simulations do
  not mutate the shared replay. Future events are restricted to each execution horizon;
  calibration outcomes are separate from historical funding predictions.
- Impact fitting uses chronological splits and training-only size regimes. Serialization
  retains precise coefficients, provenance and unsupported-depth caveats. Cost admission
  requires known validation cutoffs, stable hashes and both supported square-root sides.
- Funding inference uses exact conjugate AR(1) algebra in bps internally. Rolling forecasts
  use only observed history, reset cadence regimes and simulate recursive joint paths.
  Future-poisoning and withheld-data cases are in the offline suite.
- Carry decisions require scoped adequacy evidence and calibrated cost admission. Sizing
  uses marginal impact, executable lots and support/market caps; chosen size, feasible
  maximum and supported break-even capacity are distinct. No target capacity or Sharpe
  enters inference or sizing.
- All new publication candidates were enumerated. Source/tests/configuration/docs only;
  no downloaded book rows, archives, fitted corpus artifacts or build output. A targeted
  scan for private keys, GitHub tokens and AWS access-key IDs found no matches. This is
  a targeted publication check, not a general security certification.

## Fresh verification

- `uv sync --locked --reinstall-package perpcarry`: locked extension build passed.
- Standalone CMake/Ninja configure and bounded `-j 2` build passed; Catch2 source used
  the repository's ignored `.fetchcontent` directory.
- `uv run ctest --test-dir build/dev --output-on-failure`: 85/85 passed.
- `uv run pytest`: 657 passed, ten network tests deselected, after the extension rebuild.
- `uv run ruff check .`, `uv run ruff format --check .`, `git diff --check`: passed.
- Existing scratch mutation evidence was inspected, including all 26 M7-T2 intended
  failures. Those audits are recorded in milestone logs; they were not all rerun here.

Network acquisition tests and ThreadSanitizer were not rerun in this audit. Queue
synchronization was unchanged; prior sanitizer evidence remains historical. Linux was
verified locally; macOS and hosted CI are pending the push.

## Limits retained

B-009–B-012 remain open: sparse L2 coverage, incomplete research execution/volume and
accounting inputs, SOL dated metadata, and funding predictive adequacy. No real BTC/SOL
impact fit or adequacy approval was manufactured. M7-T4 accounting and T3 walk-forward
are not implemented. No strategy P&L, gross/net Sharpe or measured capacity is claimed.
Next implementation: T4 accounting, then T3. Raw data and local test/audit reports remain
ignored. This audit supports publishing the engineering work, not scientific adequacy.
