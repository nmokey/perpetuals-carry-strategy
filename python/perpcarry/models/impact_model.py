"""M5-T2: chronological, touch-relative impact fits and out-of-sample diagnostics.

Square-root is primary. Linear and log-OLS power fits are diagnostics. All fits are
separate by symbol, side, execution schedule, validated depth and training-only size
regime. Dense residual rows stay in the ignored data root; model save/load is M5-T3.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from perpcarry.integrity import partition_fingerprint, sha256
from perpcarry.storage import data_root, write_parquet

TARGET = "slippage_vs_touch_bps"
GROUPS = ["symbol", "side", "schedule"]
FLAGS = ["crossed_at_entry", "exhausted_book", "beyond_validated_depth"]
FORMS = ("square_root", "linear", "power_diagnostic")


class ImpactModelError(ValueError):
    """Insufficient or invalid data; no substitute coefficient is supplied."""


@dataclass(frozen=True)
class FitConfig:
    target: str = TARGET
    train_days: int = 90
    size_quantiles: tuple[float, ...] = (1 / 3, 2 / 3)

    def __post_init__(self):
        if self.target != TARGET:
            raise ImpactModelError("impact must use touch-relative slippage; spread is separate")
        if self.train_days < 1:
            raise ImpactModelError("train_days must be positive")
        if tuple(sorted(set(self.size_quantiles))) != self.size_quantiles or any(
            not 0 < value < 1 for value in self.size_quantiles
        ):
            raise ImpactModelError("size quantiles must be unique, increasing and inside (0, 1)")


@dataclass(frozen=True)
class FittedLaw:
    form: str
    coefficient: float
    exponent: float

    def predict(self, adv_fraction):
        size = np.asarray(adv_fraction, dtype=float)
        if not np.isfinite(size).all() or (size <= 0).any():
            raise ImpactModelError("prediction sizes must be finite positive ADV fractions")
        prediction = self.coefficient * np.power(size, self.exponent)
        if not np.isfinite(prediction).all():
            raise ImpactModelError("non-finite prediction")
        return prediction


@dataclass
class FitReport:
    summary: dict
    diagnostics: pd.DataFrame


def fit_law(x: np.ndarray, y: np.ndarray, form: str) -> FittedLaw:
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    if (
        x.ndim != 1
        or y.shape != x.shape
        or not x.size
        or not np.isfinite(x).all()
        or not np.isfinite(y).all()
        or (x <= 0).any()
    ):
        raise ImpactModelError("fit needs aligned finite sizes/targets and positive sizes")
    if form in {"square_root", "linear"}:
        exponent = 0.5 if form == "square_root" else 1.0
        transformed = np.power(x, exponent)
        coefficient = float(np.dot(transformed, y) / np.dot(transformed, transformed))
    elif form == "power_diagnostic":
        positive = y > 0
        if positive.sum() < 2 or np.unique(x[positive]).size < 2:
            raise ImpactModelError("power diagnostic needs two positive targets at distinct sizes")
        # Log-space OLS is diagnostic only; evaluate predictions in original bps below.
        lx, ly = np.log(x[positive]), np.log(y[positive])
        centered = lx - lx.mean()
        exponent = float(np.dot(centered, ly - ly.mean()) / np.dot(centered, centered))
        with np.errstate(over="ignore"):
            coefficient = float(np.exp(ly.mean() - exponent * lx.mean()))
    else:
        raise ImpactModelError(f"unknown form: {form}")
    if not np.isfinite([coefficient, exponent]).all():
        raise ImpactModelError("non-finite fitted parameters")
    return FittedLaw(form, coefficient, exponent)


def metrics(y: np.ndarray, predicted: np.ndarray) -> dict:
    residual = y - predicted
    sse = float(np.dot(residual, residual))
    centered = y - y.mean()
    sst = float(np.dot(centered, centered))
    result = {
        "rows": len(y),
        "rmse_bps": float(np.sqrt(sse / len(y))),
        "mae_bps": float(np.abs(residual).mean()),
        "r2": 1 - sse / sst if sst > 0 else None,
        "r2_status": "defined" if sst > 0 else "undefined_constant_target",
    }
    if not all(np.isfinite(value) for value in result.values() if isinstance(value, float)):
        raise ImpactModelError("non-finite fit diagnostics")
    return result


def _validate(frame: pd.DataFrame) -> pd.DataFrame:
    required = [*GROUPS, "date", "timestamp", "adv_fraction", TARGET, *FLAGS]
    missing = set(required) - set(frame)
    if missing or frame.empty:
        raise ImpactModelError(f"empty or incomplete calibration data; missing {sorted(missing)}")
    frame = frame[required].copy()
    for column in FLAGS:
        if not pd.api.types.is_bool_dtype(frame[column]) or frame[column].isna().any():
            raise ImpactModelError(f"{column} must be non-null boolean")
    if frame[GROUPS + ["date"]].isna().any().any():
        raise ImpactModelError("null grouping or date fields")
    if (
        not frame["side"].isin(["buy", "sell"]).all()
        or not frame["schedule"].isin(["static", "sliced"]).all()
    ):
        raise ImpactModelError("unknown side or execution schedule")
    try:
        dates = frame["date"].map(dt.date.fromisoformat)
        timestamps = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
    except (ValueError, TypeError, OverflowError) as error:
        raise ImpactModelError("invalid date or timestamp") from error
    if not (timestamps.dt.date == dates).all():
        raise ImpactModelError("entry timestamp falls outside its UTC day")
    # Excluded exhausted/crossed fills can legitimately have undefined slippage.
    eligible = frame[~(frame["crossed_at_entry"] | frame["exhausted_book"])]
    values = eligible[["adv_fraction", TARGET]].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values[:, 0] <= 0).any():
        raise ImpactModelError("eligible size/target must be finite and size positive")
    return frame.sort_values(required, kind="stable").reset_index(drop=True)


def fit(
    frame: pd.DataFrame,
    *,
    train_end: dt.date | str,
    test_end: dt.date | str,
    config: FitConfig | None = None,
) -> FitReport:
    """Fit strictly before train_end; score [train_end, test_end), with whole UTC days.

    Cutoffs are explicit so adding later data cannot shift an existing fold. Size-regime
    boundaries use unique training sizes only. No random splitting, fallback or tuning.
    """
    config = config or FitConfig()
    train_end = dt.date.fromisoformat(train_end) if isinstance(train_end, str) else train_end
    test_end = dt.date.fromisoformat(test_end) if isinstance(test_end, str) else test_end
    if train_end >= test_end:
        raise ImpactModelError("test_end must follow the exclusive training cutoff")
    start = train_end - dt.timedelta(days=config.train_days)
    if "date" not in frame or frame.empty:
        raise ImpactModelError("empty or incomplete calibration data")
    window = _validate(frame[(frame.date >= str(start)) & (frame.date < str(test_end))])
    excluded = window.crossed_at_entry | window.exhausted_book
    summary = {
        "task": "M5-T2",
        "primary_form": "square_root",
        "size_unit": "ADV fraction; multiply by 100 for percent",
        "config": asdict(config),
        "train_start": str(start),
        "train_end_exclusive": str(train_end),
        "test_end_exclusive": str(test_end),
        "weighting": "equal eligible rows; event-grid samples weight busy periods more heavily",
        "size_regimes": "quantiles of unique eligible training sizes, per group and depth",
        "input_rows": len(frame),
        "outside_window_rows": len(frame) - len(window),
        "excluded_rows": int(excluded.sum()),
        "crossed_rows": int(window.crossed_at_entry.sum()),
        "exhausted_rows": int(window.exhausted_book.sum()),
        "exclusion_note": "reason counts overlap; excluded_rows is their union",
        "groups": [],
        "fits": [],
        "caveat": "fill rows are correlated; held-out days do not establish year-round execution",
        "signed_targets": (
            "retain favorable sliced price movement and static rounding residuals; "
            "negative fitted costs are reported, "
            "not clipped or usable as a nonnegative impact law"
        ),
        "power_diagnostic": (
            "log-OLS on positive training targets; original-bps scoring includes zero "
            "and negative targets"
        ),
    }
    diagnostics = []
    for keys, original in window.groupby(GROUPS, sort=True, observed=True):
        identity = dict(zip(GROUPS, keys, strict=True))
        good = original[~(original.crossed_at_entry | original.exhausted_book)].copy()
        good["split"] = np.where(good.date < str(train_end), "train", "test")
        training = good[good.split == "train"]
        testing = good[good.split == "test"]
        group = {
            **identity,
            "train_days": sorted(training.date.unique()),
            "test_days": sorted(testing.date.unique()),
            "excluded_rows": len(original) - len(good),
            "status": "eligible_days" if len(training) and len(testing) else "insufficient_days",
        }
        summary["groups"].append(group)
        if not len(training) or not len(testing):
            continue
        first_fit = len(summary["fits"])
        for deep in (False, True):
            subset = good[good.beyond_validated_depth == deep].copy()
            train = subset[subset.split == "train"]
            test = subset[subset.split == "test"]
            depth = "beyond_validated_depth" if deep else "inside_validated_depth"
            if train.empty or test.empty:
                summary["fits"].append(
                    {
                        **identity,
                        "depth": depth,
                        "status": "insufficient_train_or_test_rows",
                        "train_rows": len(train),
                        "test_rows": len(test),
                    }
                )
                continue
            sizes = np.unique(train.adv_fraction.to_numpy(dtype=float))
            edges = (
                np.unique(np.quantile(sizes, config.size_quantiles))
                if config.size_quantiles
                else []
            )
            subset["size_bin"] = np.searchsorted(edges, subset.adv_fraction, side="left")
            regimes = (
                [("all_sizes", subset)]
                + [
                    (f"training_size_bin_{i}", subset[subset.size_bin == i])
                    for i in range(len(edges) + 1)
                ]
                if config.size_quantiles
                else [("all_sizes", subset)]
            )
            for regime, rows in regimes:
                tr, te = rows[rows.split == "train"], rows[rows.split == "test"]
                base = {
                    **identity,
                    "depth": depth,
                    "size_regime": regime,
                    "size_bin_edges_adv_fraction": [float(v) for v in edges],
                    "train_rows": len(tr),
                    "test_rows": len(te),
                    "train_days": sorted(tr.date.unique()),
                    "test_days": sorted(te.date.unique()),
                }
                if tr.empty or te.empty:
                    summary["fits"].append({**base, "status": "insufficient_train_or_test_rows"})
                    continue
                x, y = tr.adv_fraction.to_numpy(float), tr[TARGET].to_numpy(float)
                for form in FORMS:
                    record = {**base, "form": form}
                    try:
                        law = fit_law(x, y, form)
                        predictions = law.predict(rows.adv_fraction.to_numpy(float))
                        split_metrics = {
                            name: metrics(
                                part[TARGET].to_numpy(float), law.predict(part.adv_fraction)
                            )
                            for name, part in (("train", tr), ("test", te))
                        }
                    except ImpactModelError as error:
                        summary["fits"].append(
                            {**record, "status": "unavailable", "reason": str(error)}
                        )
                        continue
                    per_day = []
                    for day, day_rows in tr.groupby("date", sort=True, observed=True):
                        try:
                            daily = fit_law(
                                day_rows.adv_fraction.to_numpy(float),
                                day_rows[TARGET].to_numpy(float),
                                form,
                            )
                            per_day.append({"date": day, "rows": len(day_rows), **asdict(daily)})
                        except ImpactModelError as error:
                            per_day.append(
                                {"date": day, "rows": len(day_rows), "unavailable": str(error)}
                            )
                    coefficients = [p["coefficient"] for p in per_day if "coefficient" in p]
                    record.update(
                        status="evaluated",
                        model=asdict(law),
                        metrics=split_metrics,
                        per_training_day=per_day,
                        daily_coefficient_std=float(np.std(coefficients, ddof=1))
                        if len(coefficients) > 1
                        else None,
                        training_size_min=float(x.min()),
                        training_size_max=float(x.max()),
                        zero_training_targets=int((y == 0).sum()),
                        negative_training_targets=int((y < 0).sum()),
                        usable_as_nonnegative_impact_law=law.coefficient >= 0 and law.exponent > 0,
                        fit_rows_used=int((y > 0).sum()) if form == "power_diagnostic" else len(y),
                    )
                    summary["fits"].append(record)
                    residuals = rows[
                        [*GROUPS, "date", "timestamp", "adv_fraction", TARGET, "split"]
                    ].copy()
                    residuals.rename(columns={TARGET: "observed_bps"}, inplace=True)
                    residuals["depth"] = depth
                    residuals["size_regime"] = regime
                    residuals["form"] = form
                    residuals["fitted_bps"] = predictions
                    residuals["residual_bps"] = residuals.observed_bps - predictions
                    residuals["outside_training_size_range"] = (rows.adv_fraction < x.min()) | (
                        rows.adv_fraction > x.max()
                    )
                    diagnostics.append(residuals)
        group["status"] = (
            "evaluated"
            if any(
                r.get("form") == "square_root" and r["status"] == "evaluated"
                for r in summary["fits"][first_fit:]
            )
            else "no_evaluable_depth_regime"
        )
    if not any(
        r.get("form") == "square_root" and r["status"] == "evaluated" for r in summary["fits"]
    ):
        raise ImpactModelError(
            "need eligible earlier training and later held-out days in the same group/depth"
        )
    return FitReport(summary, pd.concat(diagnostics, ignore_index=True))


def load_calibration(
    root: Path, symbols: list[str], *, start: dt.date | None = None, end: dt.date | None = None
) -> tuple[pd.DataFrame, list[dict]]:
    """Admit only intact M5-T1 outputs whose underlying quality evidence still verifies."""
    # Fitting and loading fixed laws do not need the compiled replay adapter. Only
    # calibration admission imports the generator that owns that C++ dependency.
    from perpcarry.models import calibration_dataset

    frames, evidence = [], []
    for symbol in sorted(set(symbols)):
        partitions = sorted((root / "calibration" / f"symbol={symbol}").glob("date=*"))
        if not partitions:
            raise ImpactModelError(f"no calibration partitions for {symbol}")
        for partition in partitions:
            day = dt.date.fromisoformat(partition.name.removeprefix("date="))
            if (start is not None and day < start) or (end is not None and day >= end):
                continue
            try:
                manifest_path = partition / "manifest.json"
                manifest_digest = sha256(manifest_path)
                manifest = json.loads(manifest_path.read_text())
                if (manifest["task"], manifest["symbol"], manifest["date"]) != (
                    "M5-T1",
                    symbol,
                    str(day),
                ):
                    raise ImpactModelError("manifest identity mismatch")
                if partition_fingerprint(partition) != manifest["output_sha256"]:
                    raise ImpactModelError("calibration output hashes disagree")
                inputs = calibration_dataset.verified_inputs(
                    root, symbol, day, calibration_dataset.Config(**manifest["config"])
                )
                if inputs != manifest["inputs"]:
                    raise ImpactModelError("calibration input evidence changed")
                frame = pd.concat(
                    [
                        pq.ParquetFile(path).read().to_pandas()
                        for path in sorted(partition.glob("*.parquet"))
                    ],
                    ignore_index=True,
                )
                if (
                    len(frame) != manifest["rows"]
                    or not (frame.symbol == symbol).all()
                    or not (frame.date == str(day)).all()
                ):
                    raise ImpactModelError("calibration rows disagree with manifest")
                if (
                    partition_fingerprint(partition) != manifest["output_sha256"]
                    or sha256(manifest_path) != manifest_digest
                ):
                    raise ImpactModelError("calibration changed while loading")
            except (OSError, KeyError, TypeError, ValueError) as error:
                raise ImpactModelError(f"cannot admit {partition}: {error}") from error
            frames.append(frame)
            evidence.append(
                {"symbol": symbol, "date": str(day), "manifest_sha256": manifest_digest}
            )
    if not frames:
        raise ImpactModelError("no calibration partitions in the requested fold")
    return pd.concat(frames, ignore_index=True), evidence


def write_diagnostics(report: FitReport, destination: Path) -> None:
    """Write a research report and residual artifacts, not a deployable model/loader."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    destination.mkdir(parents=True, exist_ok=True)
    (destination / "report.json").write_text(
        json.dumps(report.summary, indent=2, allow_nan=False) + "\n"
    )
    write_parquet(report.diagnostics, destination / "residuals.parquet")
    for previous in destination.glob("residuals-*.png"):
        previous.unlink()
    for i, (keys, rows) in enumerate(
        report.diagnostics.groupby(
            [*GROUPS, "depth", "size_regime", "form"], sort=True, observed=True
        )
    ):
        figure, axes = plt.subplots(1, 2, figsize=(10, 4))
        for split in ("train", "test"):
            part = rows[rows.split == split]
            axes[0].scatter(part.fitted_bps, part.residual_bps, s=3, alpha=0.3, label=split)
            axes[1].scatter(part.adv_fraction, part.residual_bps, s=3, alpha=0.3, label=split)
        for axis in axes:
            axis.axhline(0, color="black", linewidth=0.5)
            axis.set_ylabel("Observed − fitted impact (bps)")
            axis.legend()
        axes[0].set_xlabel("Fitted touch-relative impact (bps)")
        axes[1].set_xlabel("Order size / trailing ADV (fraction)")
        axes[1].set_xscale("log")
        figure.suptitle(" / ".join(keys))
        figure.tight_layout()
        figure.savefig(destination / f"residuals-{i:03d}.png", dpi=120)
        plt.close(figure)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", action="append", required=True)
    parser.add_argument("--train-end", type=dt.date.fromisoformat, required=True)
    parser.add_argument("--test-end", type=dt.date.fromisoformat, required=True)
    parser.add_argument("--train-days", type=int, default=90)
    parser.add_argument("--model-dir", type=Path, help="also save strict per-symbol M5-T3 JSON")
    args = parser.parse_args()
    root = data_root()
    frame, evidence = load_calibration(
        root,
        args.symbol,
        start=args.train_end - dt.timedelta(days=args.train_days),
        end=args.test_end,
    )
    report = fit(
        frame,
        train_end=args.train_end,
        test_end=args.test_end,
        config=FitConfig(train_days=args.train_days),
    )
    report.summary["inputs"] = evidence
    report.summary["fitting_source_sha256"] = sha256(Path(__file__))
    report.summary["fit_date"] = str(dt.datetime.now(dt.UTC).date())
    report.summary["code_version"] = (
        subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=Path(__file__).parent, text=True
        ).strip()
        + "+working-tree (fitting source hash recorded separately)"
    )
    destination = root / "impact_fits" / f"train-end={args.train_end}_test-end={args.test_end}"
    write_diagnostics(report, destination)
    if args.model_dir is not None:
        from perpcarry.models.impact_model_io import from_fit_report, save

        for symbol in sorted(set(args.symbol)):
            artifact = from_fit_report(
                report,
                symbol,
                fit_date=report.summary["fit_date"],
                code_version=report.summary["code_version"],
            )
            save(artifact, args.model_dir / f"impact_{symbol}.json")
    print(f"M5-T2 diagnostics: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
