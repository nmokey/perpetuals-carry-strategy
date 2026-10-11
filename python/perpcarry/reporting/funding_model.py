"""M6-T2 reproducible reports of posterior estimates and adequacy diagnostics."""

from __future__ import annotations

import json
from pathlib import Path


def write(report: dict, destination: Path):
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    lines = [
        "# M6-T2 Bayesian funding model checks",
        "",
        "Fit warmup only; frozen posterior, one-step study predictions conditional on "
        "the previous observed settlement.",
        "No rolling refits, entry rules, strategy P&L or model adequacy certification.",
        "",
        "Intervals are 95% marginal credible intervals; intercept in bps per settlement, "
        "phi dimensionless.",
        "",
        "| Symbol | Warmup phi [95% interval] | Intercept bps | Study 95% coverage | "
        "Study residual lag-1 ACF |",
        "|---|---|---|---|---|",
    ]
    for symbol, result in report["symbols"].items():
        posterior, study = result["posterior"], result["study_checks"]
        phi = posterior["phi"]
        lines.append(
            f"| {symbol} | {phi['mean']:.4f} "
            f"[{phi['interval'][0]:.4f}, {phi['interval'][1]:.4f}] | "
            f"{posterior['intercept_bps']['mean']:.4f} | {study['coverage']['0.95']:.2%} | "
            f"{study['residual_statistics']['lag1_acf']:.4f} |"
        )
    for symbol, result in report["symbols"].items():
        study = result["study_checks"]
        lines.extend(
            [
                "",
                f"## {symbol} conditional in-sample posterior predictive checks",
                "",
                "| Statistic | Observed | Replicated 95% interval | "
                "Fraction replicated below observed |",
                "|---|---|---|---|",
            ]
        )
        for name, value in result["warmup_replication"]["statistics"].items():
            low, high = value["replicated_95_interval"]
            lines.append(
                f"| {name} | {value['observed']:.4f} | [{low:.4f}, {high:.4f}] | "
                f"{value['replicated_fraction_below_observed']:.4f} |"
            )
        lines.extend(["", "Study negative-tail counts (observed / expected):", ""])
        for threshold, value in study["negative_tail"].items():
            lines.append(
                f"- Below {threshold} bps: {value['observed_count']} / "
                f"{value['expected_count']:.3g}"
            )
    lines.extend(
        [
            "",
            "A nominal interval can overcover and still miss extreme tails. Residual dependence "
            "and PIT concentration indicate misspecification; in-sample replication is not "
            "independent validation.",
            "",
            "Baseline prior is explicit and configurable, not optimized from study results. "
            "Sensitivity and causal rolling evaluation remain necessary before strategy use.",
            "",
            "See report.json for all interval levels, PIT bins, residual correlations, "
            "posterior variance, prior and evidence hashes.",
            "",
        ]
    )
    (destination / "report.md").write_text("\n".join(lines))
