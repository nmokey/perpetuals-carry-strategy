"""M7-T3: lazy manifest admission, deterministic CLI output and explicit coverage status."""

import json
from dataclasses import asdict

import pytest
from walk_forward_helpers import END, START, STEP, WARMUP, observation, tick, warmup
from walk_forward_helpers import scenario as scenario

from perpcarry.integrity import sha256
from perpcarry.models import impact_model_io
from perpcarry.tools import run_backtest as cli


@pytest.fixture
def cli_case(tmp_path, impact_artifact_factory, scenario):
    config, _ = scenario
    # M5 declares training from May 3; this engineering case explicitly allows 180 days.
    # The separate trailing-window test rejects it under the research 90-day contract.
    artifact = tmp_path / "impact.json"
    impact_model_io.save(impact_artifact_factory(), artifact)
    study = tmp_path / "study.toml"
    study.write_text("""[study]
symbols = ["BTCUSDT", "SOLUSDT"]
timezone = "UTC"
warmup_start = "2025-09-01"
start = "2025-10-01"
end = "2025-10-31"
[funding]
rolling_days = 90
[impact]
rolling_days = 180
""")
    run = tmp_path / "run.toml"
    run.write_text("""[run]
symbol = "BTCUSDT"
execution_mode = "inferred"
initial_capital_usdt = "10000"
collateral_fraction = "1"
allow_fee_assumptions = true
seed = 703
draws = 128
min_settlements = 30
interval_hours = 8
[policy]
horizon_settlements = 2
entry_probability = 0.8
continuation_probability = 0.5
allow_synthetic_costs = true
""")
    fees = tmp_path / "fees.toml"
    fees.write_text(
        "schema_version = 1\n"
        + "\n".join(
            f'''[[periods]]
symbol = "BTCUSDT"
market = "{market}"
start_ms = {WARMUP}
end_ms = {END}
taker_fraction = "0"
source = "https://example.org/synthetic"
observed_at_ms = {WARMUP}
kind = "assumption"
'''
            for market in ("spot", "perp")
        )
    )

    def funding_row(event):
        return {"type": "funding", "symbol": config.symbol, **asdict(event)}

    def market_row(event):
        supplied = None
        if event.opportunity is not None:
            op = event.opportunity
            supplied = {
                "fold_start_ms": op.fold_start_ms,
                "impact": {
                    "path": "impact.json",
                    "sha256": sha256(artifact),
                    "schedule": "static",
                    "size_regime": "all_sizes",
                },
                "sizing": asdict(op.market),
                "approval": asdict(op.approval),
                "perp_half_spread_bps": op.perp_half_spread_bps,
                "spot_execution_bps": op.spot_execution_bps,
                "financing_fraction": op.financing_fraction,
            }
        return {
            "type": "market",
            "symbol": config.symbol,
            "event_id": event.event_id,
            "time_ms": event.time_ms,
            "spot_mid": event.spot_mid,
            "perp_mid": event.perp_mid,
            "spot_mark": event.marks.spot,
            "perp_mark": event.marks.perp,
            "opportunity": supplied,
            "decide": event.decide,
            "financing_usdt": event.financing_usdt,
        }

    events = tmp_path / "events.jsonl"
    rows = [funding_row(event) for event in warmup()]
    rows.extend([funding_row(observation(START)), market_row(tick(config, START + 16000))])

    def invoke(rows=rows, *, name="output.jsonl"):
        events.write_text("".join(json.dumps(row, default=str) + "\n" for row in rows))
        output = tmp_path / name
        result = cli.main(
            [
                "--study-config",
                str(study),
                "--run-config",
                str(run),
                "--events",
                str(events),
                "--fees",
                str(fees),
                "--output",
                str(output),
            ]
        )
        return result, [json.loads(line) for line in output.read_text().splitlines()], output

    return dict(
        config=config,
        artifact=artifact,
        study=study,
        run=run,
        rows=rows,
        funding_row=funding_row,
        market_row=market_row,
        invoke=invoke,
        base=tmp_path,
    )


def test_cli_incomplete_run_is_explicit_and_reproducible(cli_case):
    case = cli_case
    code, records, path = case["invoke"]()
    code2, again, second = case["invoke"](name="again.jsonl")
    assert code == code2 == 2
    assert records == again and path.read_bytes() == second.read_bytes()
    assert records[0]["config"]["execution_mode"] == "inferred"
    assert records[0]["fee_assumptions"] is True
    assert records[-1]["status"] == "incomplete_coverage"
    assert records[-1]["open_quantity_base"] == "0.9"
    assert records[-2]["decision"]["action"] == "enter"
    assert records[-2]["impact_sha256"] == sha256(case["artifact"])


def test_cli_complete_calendar_and_terminal_marks_do_not_force_closure(cli_case):
    case = cli_case
    case["run"].write_text(
        case["run"].read_text().replace("horizon_settlements = 2", "horizon_settlements = 3")
    )
    rows = list(case["rows"])
    rows[-1]["opportunity"]["approval"]["horizons"] = [1, 2, 3]
    for t in range(START + STEP, END, STEP):
        rows.append(case["funding_row"](observation(t)))
        row = case["market_row"](tick(case["config"], t + 16000))
        row["opportunity"]["approval"]["horizons"] = [1, 2, 3]
        rows.append(row)
    rows.append(
        case["market_row"](tick(case["config"], END - 1, opportunity_present=False, decide=False))
    )
    code, records, _ = case["invoke"](rows)
    assert code == 0 and records[-1]["window_complete"] is True
    assert records[-1]["terminal_valuation_time_ms"] == END - 1
    assert records[-1]["open_quantity_base"] == "0.9"
    assert records[-2]["decision"] is None
    assert records[-2]["settlements_held"] == 0  # Fresh entry at the final scheduled decision.


def test_cli_corrupt_future_payload_preserves_earlier_records_and_error_status(cli_case):
    case = cli_case
    _, expected, _ = case["invoke"]()
    bad = {
        "type": "funding",
        "symbol": "BTCUSDT",
        "event_id": "bad",
        "time_ms": START + STEP,
        "rate": "broken",
        "interval_hours": 8,
        "mark_price": "100",
    }
    code, records, _ = case["invoke"](case["rows"] + [bad], name="corrupt.jsonl")
    assert records[:-1] == expected[:-1]
    assert code == 2 and records[-1]["status"] == "error"
    assert "decimal" in records[-1]["reason"]


@pytest.mark.parametrize("defect", ["digest", "trailing", "future", "symbol", "decimal"])
def test_cli_rejects_unadmitted_current_inputs(cli_case, defect):
    case = cli_case
    rows = json.loads(json.dumps(case["rows"], default=str))
    current = rows[-1]
    if defect == "digest":
        current["opportunity"]["impact"]["sha256"] = "f" * 64
    elif defect == "trailing":
        case["study"].write_text(
            case["study"].read_text().replace("rolling_days = 180", "rolling_days = 90")
        )
    elif defect == "future":
        artifact = impact_model_io.load(case["artifact"])
        artifact["test_end_exclusive"] = "2025-11-01"
        impact_model_io.save(artifact, case["artifact"])
        current["opportunity"]["impact"]["sha256"] = sha256(case["artifact"])
    elif defect == "symbol":
        current["symbol"] = "SOLUSDT"
    else:
        current["spot_mid"] = 100.0
    code, records, _ = case["invoke"](rows)
    assert code == 2 and records[-1]["status"] == "error"
    assert all(r.get("decision") is None for r in records[:-1])


def test_cli_output_never_overwrites_existing_result(cli_case):
    case = cli_case
    _, _, path = case["invoke"]()
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        case["invoke"]()
    assert path.read_bytes() == before


def test_cli_missing_terminal_valuation_is_not_full_window_completion(cli_case):
    case = cli_case
    rows = list(case["rows"])
    for t in range(START + STEP, END, STEP):
        rows.extend(
            [
                case["funding_row"](observation(t)),
                case["market_row"](tick(case["config"], t + 16000)),
            ]
        )
    code, records, _ = case["invoke"](rows)
    assert code == 2 and records[-1]["window_complete"] is False
    assert records[-1]["last_funding_time_ms"] == END - STEP


def test_cli_fee_change_during_admission_cannot_mislabel_output_provenance(cli_case, monkeypatch):
    case = cli_case
    original = cli.load_schedule

    def changing(path, **kwargs):
        result = original(path, **kwargs)
        path.write_text(path.read_text() + "\n# changed after parsing\n")
        return result

    monkeypatch.setattr(cli, "load_schedule", changing)
    with pytest.raises(ValueError, match="changed during admission"):
        case["invoke"]()
