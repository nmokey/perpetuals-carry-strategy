"""M6-T1 report and plots; statistical calculations remain in models.funding_eda."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


def _pvalue(test: dict) -> str:
    prefix = {"above_table": "≥", "below_table": "≤"}.get(test.get("pvalue_bound"), "")
    return f"{prefix}{test['pvalue']:.4g}"


def markdown(report: dict) -> str:
    lines = [
        "# M6-T1 — BTC/SOL funding exploratory analysis",
        "",
        f"Warmup: {report['config']['warmup_start']} to "
        f"{report['config']['study_start']} exclusive. "
        f"Study: {report['config']['study_start']} to "
        f"{report['config']['study_end_exclusive']} exclusive.",
        "",
        "Rates are basis points per settlement; 1 bp = 0.0001. "
        "The full-year section is descriptive. "
        "Prior monthly windows end strictly before their cutoff.",
        "",
        "## Study distributions and persistence",
        "",
        "| Symbol | Cadence (hours) | Settlements | Mean (bps) | Median (bps) | Positive | "
        "Longest positive run (settlements) | ACF lag 1 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for symbol, analysis in report["symbols"].items():
        for segment in analysis["windows"]["study"]["segments"]:
            correlation = segment["correlations"]
            lag1 = f"{correlation['acf'][1]:.4f}" if correlation["status"] == "evaluated" else "n/a"
            lines.append(
                f"| {symbol} | {segment['interval_hours']} | {segment['rows']} | "
                f"{segment['mean_bps']:.4f} | {segment['median_bps']:.4f} | "
                f"{segment['positive_fraction']:.1%} | "
                f"{segment['positive_runs']['max_settlements']} | {lag1} |"
            )
    lines += [
        "",
        "Observed positive streaks may be censored at window edges and are not forecasts.",
        "",
        "## Stationarity checks",
        "",
        "| Symbol | Window | Segment | ADF p | KPSS p | Joint diagnostic |",
        "|---|---|---:|---:|---:|---|",
    ]
    for symbol, analysis in report["symbols"].items():
        for name, window in analysis["windows"].items():
            for i, segment in enumerate(window["segments"]):
                stationarity = segment["stationarity"]
                if stationarity["status"] == "evaluated":
                    lines.append(
                        f"| {symbol} | {name} | {i} | {_pvalue(stationarity['adf'])} | "
                        f"{_pvalue(stationarity['kpss'])} | "
                        f"{stationarity['interpretation']} |"
                    )
                else:
                    lines.append(
                        f"| {symbol} | {name} | {i} | n/a | n/a | {stationarity['reason']} |"
                    )
    lines += [
        "",
        "ADF tests a unit-root null; KPSS tests a level-stationarity null. "
        "Mixed outcomes can reflect changing means or other misspecification. "
        "Non-rejection is not proof. KPSS values at table boundaries are shown as bounds. "
        "All tests use an intercept and 5% significance; multiple windows/lags are exploratory.",
        "",
        "## Strictly prior monthly diagnostics",
        "",
        "| Symbol | Cutoff (exclusive) | Start | Segment | Rows | ACF lag 1 | Diagnostic |",
        "|---|---|---|---:|---:|---:|---|",
    ]
    for symbol, analysis in report["symbols"].items():
        for window in analysis["prior_monthly_windows"]:
            for i, segment in enumerate(window["segments"]):
                correlation, stationarity = segment["correlations"], segment["stationarity"]
                lag1 = (
                    f"{correlation['acf'][1]:.4f}"
                    if correlation["status"] == "evaluated"
                    else "n/a"
                )
                interpretation = stationarity.get("interpretation", "unavailable")
                lines.append(
                    f"| {symbol} | {window['cutoff']} | {window['start']} | {i} | "
                    f"{segment['rows']} | {lag1} | {interpretation} |"
                )
    lines += [
        "",
        "Cadence changes are segmented; correlations never bridge unequal intervals. "
        "Lag hours, confidence intervals, exclusions/unavailable diagnostics and "
        "input/source hashes are recorded in report.json.",
        "",
        "## Plots",
        "",
    ]
    for name in report.get("plots", []):
        lines.append(f"- [{name}]({name})")
    lines += [
        "",
        "## What this supports",
        "",
        "This establishes the empirical funding input and diagnostics for M6-T2. "
        "AR(1) remains the specified first model, with rolling estimation and later "
        "posterior predictive checks needed to assess its adequacy. No Bayesian posterior, "
        "entry gate, trading P&L, Sharpe or capacity is produced here. Full-study diagnostics "
        "must not be used to tune historical thresholds or priors.",
        "",
        "Methods: [ADF](https://www.statsmodels.org/v0.14.6/generated/"
        "statsmodels.tsa.stattools.adfuller.html), "
        "[KPSS](https://www.statsmodels.org/v0.14.6/generated/"
        "statsmodels.tsa.stattools.kpss.html), "
        "[PACF](https://www.statsmodels.org/v0.14.6/generated/"
        "statsmodels.tsa.stattools.pacf.html).",
        "",
    ]
    return "\n".join(lines)


def write(report: dict, frames: dict[str, pd.DataFrame], destination: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    destination.mkdir(parents=True, exist_ok=True)
    plots = []
    for symbol, frame in frames.items():
        analysis = report["symbols"][symbol]
        times = pd.to_datetime(frame.funding_time, unit="ms", utc=True)
        rates = frame.funding_rate.to_numpy(dtype=float)
        figure, axes = plt.subplots(3, 1, figsize=(11, 9), constrained_layout=True)
        axes[0].plot(times, rates * 10_000, linewidth=0.65)
        axes[0].axvline(
            pd.Timestamp(report["config"]["study_start"], tz="UTC"),
            color="black",
            linestyle="--",
            label="study begins",
        )
        axes[0].set_ylabel("Funding (bps/settlement)")
        axes[0].legend()
        axes[1].plot(times, np.cumsum(rates) * 100)
        axes[1].set_ylabel("Simple fixed-notional sum (%)")
        axes[2].hist(rates * 10_000, bins=50)
        axes[2].set_xlabel("Funding (bps/settlement); warmup + study")
        axes[2].set_ylabel("Settlements")
        figure.suptitle(f"{symbol} funding history; sum excludes price P&L and costs")
        name = f"{symbol}-funding.png"
        figure.savefig(destination / name, dpi=140)
        plt.close(figure)
        plots.append(name)
        for window_name, window in analysis["windows"].items():
            for i, segment in enumerate(window["segments"]):
                c = segment["correlations"]
                if c["status"] != "evaluated":
                    continue
                figure, axes = plt.subplots(1, 2, figsize=(11, 3.5), constrained_layout=True)
                for axis, kind in zip(axes, ("acf", "pacf"), strict=True):
                    values = np.array(c[kind])
                    intervals = np.array(c[f"{kind}_confidence_interval"])
                    axis.vlines(c["lag_hours"], 0, values)
                    axis.plot(c["lag_hours"], values, "o", markersize=3)
                    axis.fill_between(
                        c["lag_hours"],
                        intervals[:, 0] - values,
                        intervals[:, 1] - values,
                        alpha=0.2,
                    )
                    axis.axhline(0, color="black", linewidth=0.5)
                    axis.set_title(kind.upper())
                    axis.set_xlabel("Lag (hours)")
                figure.suptitle(
                    f"{symbol}: {window_name}, segment {i}; "
                    f"{segment['interval_hours']}h cadence; exploratory intervals"
                )
                name = f"{symbol}-{window_name}-segment-{i}-correlations.png"
                figure.savefig(destination / name, dpi=140)
                plt.close(figure)
                plots.append(name)
    report["plots"] = plots
    (destination / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    (destination / "report.md").write_text(markdown(report))
