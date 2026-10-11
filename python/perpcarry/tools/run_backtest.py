"""M7-T3: run explicitly labeled inferred execution from a chronological local JSONL manifest."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import tomllib
from dataclasses import asdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

from perpcarry.ingestion.funding_series import utc_ms
from perpcarry.integrity import sha256
from perpcarry.models import impact_model_io
from perpcarry.strategy import accounting, carry, costs, execution, sizing, walk_forward
from perpcarry.strategy.accounting import Marks
from perpcarry.strategy.carry import FundingApproval, Policy
from perpcarry.strategy.execution import InferredExecutor
from perpcarry.strategy.fees import load_schedule
from perpcarry.strategy.sizing import SizingInputs


def _decimal(value):
    if not isinstance(value, str):
        raise ValueError("Financial quantities must be decimal strings")
    try:
        result = Decimal(value)
    except InvalidOperation as error:
        raise ValueError("Financial quantity is not a decimal") from error
    if not result.is_finite():
        raise ValueError("Financial quantities must be finite")
    return result


def read_event(row, config, base):
    """Decode only the row reached by the stream, including its current artifact references."""
    if row["symbol"] != config.symbol:
        raise ValueError("Manifest symbol disagrees with configured symbol")
    if row["type"] == "funding":
        return walk_forward.FundingEvent(
            row["event_id"],
            row["time_ms"],
            _decimal(row["rate"]),
            row["interval_hours"],
            _decimal(row["mark_price"]) if row.get("mark_price") is not None else None,
        )
    if row["type"] != "market":
        raise ValueError("Unknown manifest event type")
    opportunity = None
    if row.get("opportunity") is not None:
        supplied = row["opportunity"]
        reference = supplied["impact"]
        path = base / reference["path"]
        curve = costs.load_curve(
            path,
            symbol=config.symbol,
            now_ms=row["time_ms"],
            schedule=reference["schedule"],
            depth="inside_validated_depth",
            size_regime=reference["size_regime"],
            allow_synthetic=config.policy.allow_synthetic_costs,
        )
        if curve.artifact_sha256 != reference["sha256"]:
            raise ValueError("Impact artifact digest does not match manifest")
        artifact = impact_model_io.load(path)
        fold = supplied["fold_start_ms"]
        training_start = utc_ms(dt.date.fromisoformat(artifact["train_start"]))
        if training_start < fold - config.impact_rolling_days * walk_forward.DAY_MS:
            raise ValueError("Impact training lies outside the declared trailing window")
        if sha256(path) != curve.artifact_sha256:
            raise ValueError("Impact artifact changed during admission")
        market = dict(supplied["sizing"])
        for field in ("quantity_step", "min_quantity"):
            market[field] = _decimal(market[field])
        approval = supplied["approval"]
        if approval is not None:
            approval = FundingApproval(**{**approval, "horizons": tuple(approval["horizons"])})
        opportunity = walk_forward.Opportunity(
            fold,
            curve,
            approval,
            SizingInputs(**market),
            supplied["perp_half_spread_bps"],
            supplied["spot_execution_bps"],
            supplied["financing_fraction"],
        )
    return walk_forward.MarketEvent(
        row["event_id"],
        row["time_ms"],
        _decimal(row["spot_mid"]),
        _decimal(row["perp_mid"]),
        Marks(
            config.symbol, row["time_ms"], _decimal(row["spot_mark"]), _decimal(row["perp_mark"])
        ),
        opportunity,
        row["decide"],
        _decimal(row["financing_usdt"]),
    )


def _encode(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    raise TypeError(f"Unsupported output type: {type(value)}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study-config", type=Path, default=Path("config/btc-sol-study.toml"))
    parser.add_argument("--run-config", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--fees", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    source_hashes = {
        "study_config": sha256(args.study_config),
        "run_config": sha256(args.run_config),
        "fees": sha256(args.fees),
    }
    study = tomllib.loads(args.study_config.read_text())
    specification = tomllib.loads(args.run_config.read_text())
    run, scope = specification["run"], study["study"]
    if run["execution_mode"] != "inferred" or scope["timezone"] != "UTC":
        parser.error("CLI requires explicit inferred execution and UTC; book mode uses the library")
    config = walk_forward.Config(
        run["symbol"],
        utc_ms(dt.date.fromisoformat(scope["warmup_start"])),
        utc_ms(dt.date.fromisoformat(scope["start"])),
        utc_ms(dt.date.fromisoformat(scope["end"]) + dt.timedelta(days=1)),
        _decimal(run["initial_capital_usdt"]),
        _decimal(run["collateral_fraction"]),
        Policy(**specification["policy"]),
        run["execution_mode"],
        seed=run["seed"],
        draws=run["draws"],
        min_settlements=run["min_settlements"],
        rolling_days=study["funding"]["rolling_days"],
        interval_hours=run["interval_hours"],
        impact_rolling_days=study["impact"]["rolling_days"],
        decision_delay_ms=run.get("decision_delay_ms", 16000),
    )
    if config.symbol not in scope["symbols"]:
        parser.error("Run symbol is outside the shared study")
    fees = load_schedule(args.fees, allow_assumptions=run["allow_fee_assumptions"])
    for name, path in (
        ("study_config", args.study_config),
        ("run_config", args.run_config),
        ("fees", args.fees),
    ):
        if sha256(path) != source_hashes[name]:
            raise ValueError("Run configuration or fee input changed during admission")
    source_hashes.update(
        {
            name: sha256(module.__file__)
            for name, module in (
                ("walk_forward", walk_forward),
                ("execution", execution),
                ("accounting", accounting),
                ("carry", carry),
                ("sizing", sizing),
            )
        }
    )
    source_hashes["command"] = sha256(__file__)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()

    def events():
        with args.events.open("rb") as source:
            for line in source:
                digest.update(line)
                yield read_event(json.loads(line), config, args.events.parent)

    with args.output.open("x") as output:

        def write(value):
            output.write(json.dumps(value, default=_encode, sort_keys=True, allow_nan=False) + "\n")
            output.flush()

        write(
            {
                "type": "header",
                "task": "M7-T3",
                "schema_version": 1,
                "scope": "engineering run; input admission does not establish research adequacy",
                "config": asdict(config),
                "fee_assumptions": fees.allow_assumptions,
                "source_sha256": source_hashes,
            }
        )
        last_funding = last_market = last_record = None
        count = 0
        try:
            for record in walk_forward.iter_backtest(config, events(), fees, InferredExecutor()):
                write({"type": "record", **asdict(record)})
                count += 1
                last_record = record
                if record.event_type == "funding":
                    last_funding = record.time_ms
                else:
                    last_market = record.time_ms
        except (ValueError, KeyError, TypeError, OSError) as error:
            write(
                {
                    "type": "footer",
                    "status": "error",
                    "reason": str(error),
                    "records": count,
                    "consumed_input_sha256": digest.hexdigest(),
                }
            )
            return 2
        complete = (
            last_funding == config.end_ms - config.interval_hours * walk_forward.HOUR_MS
            and last_market == config.end_ms - 1
        )
        write(
            {
                "type": "footer",
                "status": "complete" if complete else "incomplete_coverage",
                "window_complete": complete,
                "records": count,
                "open_quantity_base": last_record.quantity_base if last_record else Decimal(0),
                "terminal_valuation_time_ms": last_market,
                "last_funding_time_ms": last_funding,
                "consumed_input_sha256": digest.hexdigest(),
                "note": "Open positions are marked, never forcibly closed; no headline metrics.",
            }
        )
    return 0 if complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
