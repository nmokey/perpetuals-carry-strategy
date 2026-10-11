"""M6-T3: evaluate causal rolling BTC/SOL funding forecasts using validated local data."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import tomllib
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd
import scipy
import statsmodels

from perpcarry.ingestion import funding_series
from perpcarry.integrity import sha256
from perpcarry.models import funding_model, funding_walk_forward, rolling_funding
from perpcarry.reporting import rolling_funding as funding_report
from perpcarry.storage import DATA_ROOT_ENV_VAR, data_root


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/btc-sol-study.toml"))
    parser.add_argument("--root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    config_digest = sha256(args.config)
    study_config = tomllib.loads(args.config.read_text())
    scope = study_config["study"]
    root = args.root or (
        data_root() if DATA_ROOT_ENV_VAR in os.environ else Path(scope["data_root"])
    )
    warmup = dt.date.fromisoformat(scope["warmup_start"])
    start = dt.date.fromisoformat(scope["start"])
    end = dt.date.fromisoformat(scope["end"]) + dt.timedelta(days=1)
    config = funding_walk_forward.Config(rolling_days=study_config["funding"]["rolling_days"])
    if scope["timezone"] != "UTC":
        parser.error("funding windows require UTC")
    # M6 uses funding-specific evidence, not the overall corpus verdict blocked by L2/ADV.
    audit_path = root / "reports" / "funding-study-audit.json"
    audit_digest = sha256(audit_path)
    audit = json.loads(audit_path.read_text())
    analyses, inputs = {}, {}
    for symbol in scope["symbols"]:
        frame, evidence = funding_series.load(
            root,
            symbol,
            warmup,
            end,
            expected_hashes=audit[symbol]["partition_sha256"],
        )
        inputs[symbol] = evidence
        analyses[symbol] = funding_walk_forward.analyze(
            frame,
            study_start=start,
            study_end=end,
            config=config,
        )
    if sha256(audit_path) != audit_digest:
        raise funding_series.FundingSeriesError("funding audit changed during analysis")
    if sha256(args.config) != config_digest:
        raise funding_series.FundingSeriesError("study config changed during analysis")
    report = {
        "task": "M6-T3",
        "schema_version": 1,
        "config": {
            **asdict(config),
            "horizons": list(config.horizons),
            "prior": funding_walk_forward.prior_spec(funding_model.Prior()),
            "warmup_start": str(warmup),
            "study_start": str(start),
            "study_end_exclusive": str(end),
            "timezone": "UTC",
        },
        "provenance": {
            "study_config_sha256": config_digest,
            "command_source_sha256": sha256(Path(__file__)),
            "funding_audit_sha256": audit_digest,
            "input_sha256": inputs,
            "source_sha256": {
                name: sha256(module.__file__)
                for name, module in (
                    ("funding_series", funding_series),
                    ("funding_model", funding_model),
                    ("rolling_funding", rolling_funding),
                    ("funding_walk_forward", funding_walk_forward),
                    ("funding_report", funding_report),
                )
            },
            "versions": {
                "numpy": np.__version__,
                "pandas": pd.__version__,
                "statsmodels": statsmodels.__version__,
                "scipy": scipy.__version__,
            },
        },
        "symbols": analyses,
    }
    destination = args.output or root / "reports" / "rolling-funding"
    funding_report.write(report, destination)
    print(f"M6-T3 rolling funding report: {destination / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
