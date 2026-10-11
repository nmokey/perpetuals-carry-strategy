"""M6-T3: reproducible causal funding forecast diagnostics."""

import json
from pathlib import Path


def write(report: dict, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    lines = [
        "# M6-T3 rolling funding forecasts",
        "",
        "Refit from observed funding in the configured prior window before each settlement. "
        "Cumulative horizons are diagnostics, not strategy holding rules.",
        "",
        "| Symbol | Scored | Frozen 95% coverage | Rolling 95% coverage | "
        "Rolling lower / upper misses | Positive Brier |",
        "|---|---|---|---|---|---|",
    ]
    for symbol, result in report["symbols"].items():
        rolling, frozen = result["one_step"], result["frozen_comparator"]
        if not rolling["rows"]:
            lines.append(
                f"| {symbol} | 0 | unavailable | unavailable | unavailable | unavailable |"
            )
            continue
        lines.append(
            f"| {symbol} | {rolling['rows']} | {frozen['coverage']['0.95']:.2%} | "
            f"{rolling['coverage']['0.95']:.2%} | {rolling['lower_95_misses']} / "
            f"{rolling['upper_95_misses']} | {rolling['positive_probability_brier']:.4f} |"
        )
    for symbol, result in report["symbols"].items():
        lines.extend(
            [
                "",
                f"## {symbol}",
                "",
                "| Horizon (settlements) | Complete scores | 95% coverage | "
                "Lower / upper misses | Endpoints excluded | Positive Brier |",
                "|---|---|---|---|---|---|",
            ]
        )
        for horizon, scored in result["cumulative"].items():
            if not scored["rows"]:
                lines.append(
                    f"| {horizon} | 0 | unavailable | unavailable | "
                    f"{scored['incomplete_endpoints']} | unavailable |"
                )
                continue
            lines.append(
                f"| {horizon} | {scored['rows']} | {scored['coverage_95']:.2%} | "
                f"{scored['lower_95_misses']} / {scored['upper_95_misses']} | "
                f"{scored['incomplete_endpoints']} | "
                f"{scored['positive_probability_brier']:.4f} |"
            )
        lines.extend(
            [
                "",
                "Monthly exact one-step coverage:",
                "",
                "| Month | Settlements | 95% coverage |",
                "|---|---|---|",
            ]
        )
        for month, scored in result["monthly"].items():
            coverage = f"{scored['coverage']['0.95']:.2%}" if scored["rows"] else "unavailable"
            lines.append(f"| {month} | {scored['rows']} | {coverage} |")
        lines.extend(
            [
                "",
                "Predeclared prior sensitivity (no default selected from results):",
                "",
                "| Variant | Exact one-step 95% coverage |",
                "|---|---|",
            ]
        )
        for name, variant in result["prior_sensitivity"].items():
            scored = variant["one_step"]
            coverage = f"{scored['coverage']['0.95']:.2%}" if scored["rows"] else "unavailable"
            lines.append(f"| {name} | {coverage} |")
    lines.extend(
        [
            "",
            "Frozen comparison uses the same initially retained rolling-window training "
            "history, rather than T2's full 92-day warmup. Exact one-step and Monte Carlo "
            "cumulative uncertainty remain separate. Overlapping scores are dependent; "
            "aggregate coverage does not certify downside risk or profitability.",
            "",
            "See JSON for forecast timestamps, training windows, source hashes, seeds, "
            "tail counts, PIT bins, residual correlations and excluded horizons.",
            "",
        ]
    )
    (destination / "report.md").write_text("\n".join(lines))
