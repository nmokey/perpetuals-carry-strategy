"""M6-T2: check Bayesian BTC/SOL funding models using existing, validated local partitions."""

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
from perpcarry.models import funding_checks, funding_model
from perpcarry.reporting import funding_model as funding_report
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
    prior = funding_model.Prior()
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
        if frame.funding_interval_hours.nunique() != 1:
            raise funding_series.FundingSeriesError("M6-T2 command requires one constant cadence")
        warm = frame[frame.funding_time < funding_series.utc_ms(start)]
        study = frame[frame.funding_time >= funding_series.utc_ms(start)]
        model = funding_model.fit(
            warm.funding_rate.to_numpy(),
            interval_hours=int(warm.funding_interval_hours.iloc[0]),
            prior=prior,
        )
        warm_rates, study_rates = warm.funding_rate.to_numpy(), study.funding_rate.to_numpy()
        previous = np.concatenate(([warm_rates[-1]], study_rates[:-1]))
        analyses[symbol] = {
            "warmup_rows": len(warm),
            "study_rows": len(study),
            "posterior": model.summary(),
            "warmup_checks": funding_checks.check(model, warm_rates[:-1], warm_rates[1:]),
            "warmup_replication": funding_checks.replicate(model, warm_rates),
            "study_checks": funding_checks.check(model, previous, study_rates),
        }
    if sha256(audit_path) != audit_digest:
        raise funding_series.FundingSeriesError("funding audit changed during analysis")
    if sha256(args.config) != config_digest:
        raise funding_series.FundingSeriesError("study config changed during analysis")
    report = {
        "task": "M6-T2",
        "schema_version": 1,
        "config": {
            "prior": asdict(prior),
            "draws": 2000,
            "seed": 602,
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
                    ("funding_checks", funding_checks),
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
    destination = args.output or root / "reports" / "funding-model"
    funding_report.write(report, destination)
    print(f"M6-T2 funding model report: {destination / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
