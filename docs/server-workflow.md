# Server acquisition and calibration workflow

Current scope and coverage: [2026-10-11 readiness summary](current-status.md).
Commands below describe individual stages. The 60-archive batch and 30 replay verdicts
are complete; a fresh download/replay is not needed merely to repeat these instructions.

The server rebuilds the corpus from archives; no data is copied from the previous machine.
Keep the data root under the gitignored `data/`, or set `PERPCARRY_DATA_ROOT` to an absolute
path on approved storage. Archive downloads, temporary exports and reports follow that root.
The free space reported for `/home` belongs to a shared filesystem; it is not a personal quota.

## Environment verification

```bash
uv sync --locked
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run cmake -S . -B build/dev -G Ninja
uv run cmake --build build/dev -j 4
uv run ctest --test-dir build/dev --output-on-failure
uv run pytest -m network
```

The server's ThreadSanitizer runtime initially reports `unexpected memory mapping`. The queue
test passes with ASLR disabled **for that process only**, without changing server settings:

```bash
uv run cmake -S . -B build/tsan -G Ninja -D PERPCARRY_SANITIZER=thread -D PERPCARRY_BUILD_PYTHON=OFF
uv run cmake --build build/tsan -j 4
setarch x86_64 -R env TSAN_OPTIONS=halt_on_error=1 ./build/tsan/cpp/tests/perpcarry_tests "[spsc]"
```

Catch2's post-build test discovery can encounter the same runtime error before the last command.
If linking produced the executable, run the last command directly. This is a platform constraint,
not a reason to weaken the queue's test or change CI.

## Active BTC/SOL corpus

Use `config/btc-sol-study.toml` and `docs/btc-sol-study.md` as the scope of record. Scored dates are 2025-10-01 through 2026-09-30; warmup starts July 2025, and June futures-bar volume prehistory supports July ADV (D-040). No further 0G downloads are authorized by the active scope; keep existing 0G data for regression testing.

Set the research root once in the shell:

```bash
export PERPCARRY_DATA_ROOT="$PWD/data/btc-sol"
uv run python -m perpcarry.ingestion.fetch_funding --symbol BTCUSDT --start 2025-07-01 --end 2026-09-30
uv run python -m perpcarry.ingestion.fetch_funding --symbol SOLUSDT --start 2025-07-01 --end 2026-09-30
uv run python -m perpcarry.ingestion.fetch_price_bars --symbol BTCUSDT --start 2025-06-01 --end 2026-09-30
uv run python -m perpcarry.ingestion.fetch_price_bars --symbol SOLUSDT --start 2025-06-01 --end 2026-09-30
```

Price ingestion verifies complete UTC minute grids and hashes for both spot and futures. Their caches and partitions are separate; spot microseconds are normalized to milliseconds. `available_at` is after the minute closes, so current-bar values cannot be used early. These bars are valuation inputs, not observed execution books or historical mark prices. Reports live under the active root's `reports/`.

Raw-trade pilots are optional reconciliation work, not a full-study download prerequisite.
Monthly trades materialize a full archive; use the bounded daily path for additional
explicitly scoped pilots. The commands below are examples, not instructions to duplicate
completed book partitions:

```bash
uv run python -m perpcarry.tools.benchmark_trades --symbol BTCUSDT --date 2025-10-01
uv run python -m perpcarry.tools.benchmark_trades --symbol SOLUSDT --date 2025-10-01
uv run python -m perpcarry.ingestion.fetch_book --symbol BTCUSDT --start 2025-07-01 --end 2025-07-01
uv run python -m perpcarry.ingestion.fetch_book --symbol SOLUSDT --start 2025-07-01 --end 2025-07-01
```

A raw-trade day is stored only after exact volume and ID-integrity checks. The active
study instead opts into verified futures-bar ADV (D-040); full raw trades are unnecessary.
Sampled books are paired full-day L2/reference feeds. D-039 selects inferred execution
calibrated on prior samples and excludes continuous daily L2. See current-status.md.

These commands replace partitions. Avoid overlapping writes to the same symbol/day or market/month. Changed data invalidate previous evidence hashes. Keep source archives and raw book exports ignored; never copy them to CI. The historical 0G October 10 volume defect remains rejected and is not allowlisted.

## Quality and M5-T1

After each pull, validate each book day, then build the corpus report. Repeat `--date` to process
several days. Book validation writes raw diagnostics under `data/validation`, keeps an aggregate
report with input hashes, and removes generated CSV exports after passing unless `--keep-exports`
is supplied. Vendor raw rows must never be committed or reach CI.

```bash
uv run python -m perpcarry.tools.validate_book --symbol BTCUSDT --date 2025-07-01
uv run python -m perpcarry.tools.corpus_inventory --reconcile-volume
uv run python -m perpcarry.models.calibration_dataset --symbol BTCUSDT --date 2025-07-01 --adv-source futures_bars
```

`$PERPCARRY_DATA_ROOT/reports/corpus.json` records partition dates, rows, sizes and hashes, the complete quality
report, and calibration eligibility with reasons. Reconciliation is exact, not tolerance-based.
Allowlisted failures remain excluded from calibration. The inventory eligibility field
still evaluates the default raw-trade route, so sparse trades can make that field false.
It is not the admission verdict for `--adv-source futures_bars`: that explicit route
rechecks cached futures archives and regenerated ADV provenance, plus corpus book
quality and full-day replay hashes for updates/references. Refresh the quality report
after stable completed partitions; avoid hashing partitions being replaced by acquisition.

M5-T1 writes one deterministic `part-0.parquet` and `manifest.json` per symbol-day under
`$PERPCARRY_DATA_ROOT/calibration/`. Defaults are 40 log-spaced sizes from 0.001% to 10% ADV, buy orders, static
execution and five equal slices over a 10-second schedule. Every 5,000 events a sample is rounded
to the end of its exchange-millisecond group. This weights busy periods more heavily. Sampling
has no randomness and therefore needs no seed. Orders whose final slice would cross UTC midnight
are not sampled. Future events are buffered for slices but never applied to the entry book.

The manifest records the configuration, git revision, source and compiled-extension hashes,
input quality evidence and output hash. Rerunning a day replaces its partition. Changing `--side`
also replaces that day's existing output; retain separate data roots for separate direction runs.

## M5-T2 impact fits

After generating eligible BTC/SOL calibration days, fit one explicit chronological fold:

```bash
uv run python -m perpcarry.models.impact_model --symbol BTCUSDT --symbol SOLUSDT \
  --train-end 2025-09-01 --test-end 2025-10-01 --train-days 60
```

This example ends all training and held-out validation before the October fold. Its
60-day training plus September validation fits the configured 90-day total window;
90 training days plus later validation would not. These dates illustrate chronology,
not an admitted research split. Generation and validation must succeed first.

The cutoff is exclusive for training; testing ends exclusively at `--test-end`. All days
stay in one split. Models are separate by symbol/side/schedule/depth and training-only
size band. Square-root is primary; linear and power laws are diagnostics. Crossed/exhausted
rows are counted and excluded, signed valid targets are retained, and negative fitted
cost laws are flagged rather than forced positive. Missing or stale evidence fails admission.

Outputs are a diagnostic `report.json`, residual Parquet, and residual-vs-fit/size PNGs
under `$PERPCARRY_DATA_ROOT/impact_fits/`. These dense artifacts remain ignored and are
not approved public exports. Rerunning replaces that fold's artifacts; avoid concurrent
writers. BTC/SOL results currently remain blocked by missing eligible calibration days.
## M5-T3 fixed model artifacts

Once calibration admission succeeds, add an explicit per-fold destination:

```bash
uv run python -m perpcarry.models.impact_model --symbol BTCUSDT --symbol SOLUSDT \
  --train-end 2025-09-01 --test-end 2025-10-01 --train-days 60 \
  --model-dir models/train-end=2025-09-01_test-end=2025-10-01
```

This writes `impact_BTCUSDT.json` and `impact_SOLUSDT.json` with schema version,
lossless coefficients, exclusive training/test windows, source hashes, supporting
days/counts and coverage caveats. A file is replaced atomically; choose a new directory
for a new fold. Only actual admitted fitted artifacts are candidates for committing;
missing calibration data currently prevents BTC/SOL exports. No download is triggered.

`perpcarry.models.impact_model_io.load(path)` validates without raw data. `law(...)`
requires explicit side, schedule, depth and size regime; missing strata raise instead
of substituting a law. Returned diagnostic or negative laws retain their form and
usability flags in the artifact. M7-T1 consumes admitted primary laws through
`strategy.costs.from_artifact(...)`; synthetic/default, depth, size and chronology gates
remain explicit. M7-T1–T4 engineering, including T3 integration, is implemented. Weekly predictive
adequacy remains unestablished; actual research manifests and M8 runs remain gated.

## M6-T1 funding analysis

Use the acquired funding corpus without downloads or book/ADV admission:

```bash
uv run python -m perpcarry.tools.analyze_funding --config config/btc-sol-study.toml
```

The command requires `reports/funding-study-audit.json` and matching hashes for all
selected funding fragments. It checks complete UTC coverage and stable reads, then
writes `reports/funding-eda/report.json`, `report.md` and six funding/ACF/PACF plots
under the active root. An explicit `--root` wins over `PERPCARRY_DATA_ROOT`; otherwise
the configured BTC/SOL root is used when the environment variable is unset. `--output`
selects another artifact directory. Avoid concurrent writers to that destination.

Whole-study statistics are descriptive. Each monthly diagnostic uses only the prior
90 completed days; cadence changes are segmented, not pooled. ADF/KPSS nulls, table
bounds, unavailable cases and source/config hashes remain in the report. Read the
reviewed aggregate findings in `docs/analysis/M6-T1-funding-eda.md` before M6-T2; the
funding sums are not strategy P&L or evidence of net profitability.

## M6-T2 Bayesian funding checks

```bash
uv run python -m perpcarry.tools.check_funding_model --config config/btc-sol-study.toml
```

Uses the same funding-specific audit admission and root/output precedence as T1. Writes
`reports/funding-model/report.json` and `report.md`. The command fits warmup only, freezes
the posterior and evaluates one-step study predictions conditional on previous observed
funding. It rejects cadence changes and never downloads or fits strategy thresholds.
In-sample conditional replication is explicitly separate from holdout diagnostics.
Reviewed results in `docs/analysis/M6-T2-bayesian-funding.md` show undercoverage/tail risk;
M6-T3 rolling assessment and prior sensitivity remain necessary before strategy use.

## M6-T3 rolling/cumulative funding diagnostics

```bash
uv run python -m perpcarry.tools.evaluate_rolling_funding --config config/btc-sol-study.toml
```

Same funding audit admission and root/output precedence as T1/T2; no downloads. Writes
`reports/rolling-funding/report.json` and `report.md`. Predicts before admitting each
settlement, refits from the configured prior window, then retrospectively scores exact
one-step and Monte Carlo cumulative distributions. Retains training timestamps, window
counts, posterior, fixed seeds, diagnostic horizon exclusions and source evidence.
Cumulative horizons 3 and 21 are settlement counts, not an entry or holding policy.
Prior variants are sensitivity diagnostics; no best variant is adopted from the study.
See `docs/analysis/M6-T3-rolling-funding.md` for improved one-step coverage and failed
weekly calibration. Avoid concurrent writers to the report destination.

Library: `perpcarry.models.rolling_funding.RollingFundingModel`, with `update(...)`,
`posterior(as_of=...)`, `training_summary(as_of=...)` and
`predict_cumulative_funding(horizon, as_of=..., draws=..., seed=...)`. The forecast exposes
fraction-unit samples, `summary()` and `probability_above(fraction)`. Call `update` only
when the settlement is actually observed; one instance per symbol. No-look-ahead depends
on this availability contract, not solely the timestamp carried by a record.

## M7-T1 carry rules (library only)

Read `docs/specs/M7/M7-T1-carry-rules.md` and D-035. No backtest CLI exists yet.
`strategy.carry.Policy` requires explicit holding-settlement count and entry/continuation
probabilities. `CarryStrategy(symbol, policy).decide(...)` returns enter/wait/hold/exit
intent, reason and cost-adjusted probability/expected edge, without fills or accounting.

One `RollingFundingModel` per symbol, updated only on actual observation;
`strategy.funding.from_model(symbol, model, horizon=..., now_ms=...)` creates its scoped
forecast. `FundingApproval` must match model/configuration fingerprint, symbol, cadence,
horizon, known validation cutoff and expiry; it records evidence rather than certifying it.
No real BTC/SOL approval has been issued (B-012 remains open).

`strategy.costs.from_artifact(...)` requires symbol, decision/expiry times, admitted
notional/ADV, horizon, schedule, order-depth and size regime, both half-spreads/fees,
hedge entry/close costs and remaining financing. It loads/hash-checks M5 JSON and rejects
future evidence, unsupported/negative laws, size extrapolation and depths beyond the
validated book. Synthetic costs require opt-in in both adapter and policy. All outputs
are fractions of perp notional; terminal close uses today's close-cost estimate. Caller
inputs must be known at the decision time; actual future fills are never gate inputs.

Held positions keep their original planned horizon. Pass forecasts and costs for the
remaining settlements, with entry costs excluded from continuation. Missing or rejected
evidence returns wait when flat and exit intent when held; an intent is not a fill.
Synthetic examples and integration coverage: `uv run pytest tests/strategy -q`.
Next: actual BTC/SOL calibration and research-input admission for M8; dated parameters,
cost/adequacy evidence and executable metadata remain required.

## M7-T2 sizing (library only)

`strategy.costs.load_curve(...)` loads supported square-root sell/buy laws once, preserving
T1 artifact/symbol/chronology/stratum checks. `strategy.sizing.ExecutionCharges` supplies
both half-spreads/fees/hedge costs and financing. `SizingInputs` requires price/expiry,
a complete strictly prior 30-day UTC base-ADV window/digest, dated contract metadata/digest,
Decimal lot step and minimum quantity, min/max notional, max ADV and validated quantity.
Records carry caller-admitted evidence; the library does not certify manually supplied
hashes, fill corpus gaps or synthesize missing SOL metadata.

`size_position(strategy, now_ms=..., forecast=..., approval=..., market=..., curve=...,
charges=...)` maximizes expected net dollars across executable lots passing T1. Outputs
chosen size, expected dollars, marginal net fraction, largest feasible size and supported
break-even size in ADV/notional. `binding_limits` describes the feasible maximum, which
need not bind the chosen optimum. An above-support root has no extrapolated capacity;
zero impact still has finite caps. Diagnostics are not realized or full-year results.
Test with `uv run pytest tests/strategy/test_sizing.py -q`. T3 integrates this library
with T4 accounting; see the walk-forward CLI below.

## M7-T4 settlement accounting (library only)

`strategy.accounting.Ledger.start(...)` requires symbol, Decimal initial capital, the
next nominal funding boundary and an explicit `strategy.fees.FeeSchedule`. Apply actual
`Fill` records for each leg independently; use executed base quantity, execution price
and contemporaneous reference mid. Methods return new immutable ledgers. Opening a
short perp never credits spot-like sale proceeds.

Consume every `FundingSettlement`, including flat periods, with a separately admitted
actual mark and per-row cadence. T3 must normalize source timestamp jitter, provide the
in-force calendar and consume the initial flat settlement before entering. Fills within
15 seconds of funding are rejected. `value(Marks)`
requires contemporaneous spot/perp marks and reports cash, exposures and gross/net
equity. `finance(...)` records explicit charges. No venue wallet/margin/liquidation model
is implied; negative cash remains visible and needs caller capital admission.

`fees.load_schedule(Path("config/fee-reference.toml"))` reads the cited reference table.
Its historical applicability is an assumption, so quotes fail by default. Explicit
`allow_assumptions=True` is for labeled sensitivity/synthetic work; it does not certify
fee history. Both actual fees and gross/net accounting use USDT equivalents, without
base-asset or BNB inventory. The research base case and settlement marks remain B-010
gates. See `docs/specs/M7/M7-T4-settlement-accounting.md` and D-037.

Verification: `uv run pytest tests/strategy/test_accounting.py tests/test_architecture.py -q`.
No BTC/SOL P&L or Sharpe is produced by this library verification.

## M7-T3 walk-forward integration

M7 engineering is implemented. This CLI consumes an explicitly admitted local event
manifest; it does not turn the downloaded corpus into research-ready inputs. The example
scenario is engineering configuration, not an approved historical BTC/SOL policy:

```bash
uv run python -m perpcarry.tools.run_backtest \
  --study-config config/btc-sol-study.toml \
  --run-config config/backtest-example.toml \
  --events /path/to/BTCUSDT-events.jsonl \
  --fees config/fee-reference.toml \
  --output /path/to/new-BTCUSDT-run.jsonl
```

Use a separate SOL scenario with the same study dates. Fee-reference assumptions require
explicit opt-in and do not certify historical costs. Output must not already exist.
Exit code 0 means configured coverage complete; 2 means incomplete coverage or an input
error. Header records scenario/source hashes; footer hashes consumed input bytes. Earlier
records survive a later error. No Sharpe or full-year capacity claim is emitted.

Each JSONL row has `type`, unique `event_id`, `symbol`, and integer UTC `time_ms`, ordered
chronologically. All prices, rates and realized financing are decimal **strings**:

- `funding`: `rate`, declared `interval_hours`, `mark_price` (may be null only in warmup).
- `market`: `spot_mid`, `perp_mid`, independent `spot_mark`/`perp_mark`, Boolean `decide`,
  `financing_usdt` and nullable `opportunity`. Require one decision at every settlement
  plus `decision_delay_ms`; other rows may provide valuation without decisions.
- `opportunity`: `fold_start_ms`, `impact`, nullable `approval`, `sizing`,
  `perp_half_spread_bps`, `spot_execution_bps`, `financing_fraction`. `impact` references
  `path` (relative to manifest), expected `sha256`, `schedule`, and `size_regime` under
  the existing M5 schema. `sizing` follows `SizingInputs`, with decimal-string
  `quantity_step`/`min_quantity`; `approval` follows `FundingApproval`. See the T3 spec
  and tested manifests in `tests/strategy/test_backtest_cli.py` for the complete contract.

The full study is October 2025–September 2026 with July–September warmup. Include every
funding row, every scheduled decision and terminal valuation at 2026-10-01 00:00 UTC minus
one millisecond. This coverage check does not establish daily-close data for M8 Sharpe.
Model training and held-out validation must both fit inside the configured prior impact
window. Missing approvals prevent entry; inferred exits still require executable inputs.

Library `iter_backtest(...)` also accepts `BookExecutor(provider)`, whose provider returns
a copied C++ Pipeline checkpoint for each leg at the exact decision time. Ingestion and
book replay remain separated by the existing SPSC queue. This does not supply absent spot
or perp books, reconstruct books from trades, or persist counterfactual execution into
later vendor updates. Fixed collateral failures abort without simulated liquidation.

Verification: `uv run pytest tests/strategy/test_walk_forward.py tests/strategy/test_backtest_cli.py tests/test_architecture.py -q`.

## BTC/SOL monthly book acquisition (2026-10-10)

The authorized local batch covers 15 first-of-month days per symbol, July 2025–September
2026, for both futures `incremental_book_L2` and `book_snapshot_25` (60 archives). Its
resumable driver, log and live status are under `data/btc-sol/reports/`:
`acquire-monthly-books.py`, `monthly-book-acquisition.log`, and
`monthly-book-acquisition.json`. The driver is an ignored operational artifact, using
the existing ingestion functions; no vendor rows enter Git. Only successful full-day
conversions move from staging into the accepted partition tree. Completion here means
structural ingest; independent replay against the top-25 reference is still required.

To resume after a stopped batch, from the repository root:

```bash
nohup setsid flock -n data/btc-sol/reports/monthly-book-acquisition.lock \
  uv run python -u data/btc-sol/reports/acquire-monthly-books.py \
  > data/btc-sol/reports/monthly-book-acquisition.log 2>&1 < /dev/null &
```

The lock prevents duplicate workers. A 429 halts further requests and records Retry-After
and its UTC deadline; rerunning before that deadline exits without contacting Tardis.
Do not treat a cached archive, staged conversion, or an older study-status report as a
replay-validated day. Refresh coverage and run the existing `tools.validate_book` workflow
once paired partitions are ready. This batch does not acquire regular-day L2 or spot books.

## Mark-price bars

`uv run python -m perpcarry.ingestion.fetch_mark_prices --root data/btc-sol` acquires
July 2025–September 2026 BTC/SOL mark-price minute bars, with published checksums and
explicit whole-missing-day repairs from daily archives. Cache and output namespaces
are separate from trade klines. `reports/mark-prices-status.json` records source and
output hashes. Decimal OHLC strings and `available_at_ms = close_time + 1` are retained.
These are bars, not certified funding-charge marks; do not use their opens as exact
settlement evidence or expose the completed close early. See
`docs/analysis/btc-sol-mark-prices.md` for the remaining source/valuation gaps.

## Monthly sample replay worker

The authorized sample validation can run alongside acquisition using the local ignored
`data/btc-sol/reports/validate-monthly-books.py` driver. Its locked worker invokes
`tools.validate_book` once per completed update/reference pair and records
`monthly-book-validation.json`/`.log`. It retains aggregate verdicts and fingerprints,
and the existing validator deletes raw CSV exports after each pass. A failed replay
stops validation; stopped acquisition leaves a visible waiting status. No extra
archives are requested. This checks the top-25 criterion and retains timestamp ambiguity;
it is not validation of deep books or exact venue execution timing.

## Study ADV from existing futures bars

The active study selects `impact.adv_source = "futures_bars"` (D-040). The calibration
CLI still defaults to raw trades; pass `--adv-source futures_bars` explicitly.
`bar_volume.verified_average_daily_volume(root, symbol, as_of)` revalidates original
cached futures archives and returns exact base ADV, prior-30-day UTC bounds, method
and causal digest. `verified_volume_inputs` also retains offline ZIP/report provenance.
Calibration and downstream fitting regenerate identical evidence; book replay and
quality admission remain required. M7 manifests must copy the dated feature into
SizingInputs; none is manufactured by changing the study setting.

`tools.audit_bar_volume --root data/btc-sol --symbol BTCUSDT --output /path/to/new.json`
reproduces the complete daily audit without downloads; substitute SOLUSDT as needed.
See `docs/analysis/bar-volume-adv.md` for full commands, validation and the preserved
October 10 raw-trade discrepancy. Do not use spot volume as perpetual ADV.
