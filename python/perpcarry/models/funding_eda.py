"""M6-T1: descriptive funding persistence diagnostics, independent of strategy fitting."""

from __future__ import annotations

import datetime as dt
import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import acf, adfuller, kpss, pacf

from perpcarry.ingestion import funding_series
from perpcarry.ingestion.calendar import months_between


@dataclass(frozen=True)
class Config:
    max_lags: int = 24
    alpha: float = 0.05
    rolling_days: int = 90
    min_stationarity_rows: int = 32

    def __post_init__(self):
        if min(self.max_lags, self.rolling_days) < 1 or self.min_stationarity_rows < 8:
            raise ValueError("positive lags/window and at least eight stationarity rows required")
        if not 0 < self.alpha < 1:
            raise ValueError("alpha must be inside (0, 1)")


def positive_runs(rates: np.ndarray) -> dict:
    lengths, current = [], 0
    for rate in rates:
        if rate > 0:
            current += 1
        elif current:
            lengths.append(current)
            current = 0
    if current:
        lengths.append(current)
    return {
        "count": len(lengths),
        "max_settlements": max(lengths, default=0),
        "median_settlements": float(np.median(lengths)) if lengths else None,
        "left_boundary_positive": bool(rates[0] > 0),
        "right_boundary_positive": bool(rates[-1] > 0),
        "caveat": "boundary runs may be censored; observed streaks are not future predictions",
    }


def stationarity(rates: np.ndarray, config: Config) -> dict:
    """Two opposing nulls; neither non-rejection nor a boundary p-value proves a model."""
    if len(rates) < config.min_stationarity_rows or np.ptp(rates) == 0:
        return {"status": "unavailable", "reason": "short or constant series"}
    try:
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            maxlag = min(config.max_lags, len(rates) // 2 - 2)
            adf_result = adfuller(rates, maxlag=maxlag, regression="c", autolag="AIC")
            kpss_result = kpss(rates, regression="c", nlags="auto")
        adf_reject = adf_result[1] < config.alpha
        kpss_reject = kpss_result[1] < config.alpha
        interpretation = {
            (True, False): "compatible_with_level_stationarity",
            (False, True): "evidence_against_level_stationarity",
            (True, True): "mixed_possible_breaks_or_misspecification",
            (False, False): "inconclusive",
        }[(adf_reject, kpss_reject)]
        return {
            "status": "evaluated",
            "alpha": config.alpha,
            "interpretation": interpretation,
            "adf": {
                "null": "unit_root",
                "statistic": float(adf_result[0]),
                "pvalue": float(adf_result[1]),
                "reject_null": bool(adf_reject),
                "used_lags": int(adf_result[2]),
                "regression_rows": int(adf_result[3]),
                "critical_values": {k: float(v) for k, v in adf_result[4].items()},
                "regression": "c",
                "autolag": "AIC",
                "max_lags": maxlag,
            },
            "kpss": {
                "null": "level_stationary",
                "statistic": float(kpss_result[0]),
                "pvalue": float(kpss_result[1]),
                "reject_null": bool(kpss_reject),
                "used_lags": int(kpss_result[2]),
                "critical_values": {k: float(v) for k, v in kpss_result[3].items()},
                "pvalue_table_range": [0.01, 0.1],
                "pvalue_bound": "above_table"
                if kpss_result[1] == 0.1
                else "below_table"
                if kpss_result[1] == 0.01
                else "interpolated",
                "regression": "c",
                "lag_policy": "auto",
            },
            "warnings": [str(w.message) for w in captured],
        }
    except (ValueError, np.linalg.LinAlgError) as error:
        return {"status": "unavailable", "reason": str(error)}


def describe_segment(frame: pd.DataFrame, config: Config) -> dict:
    """One contiguous, constant-cadence segment. Rates remain settlement fractions."""
    rates = frame.funding_rate.to_numpy(dtype=float)
    hours = int(frame.funding_interval_hours.iloc[0])
    bps = rates * 10_000
    result = {
        "rows": len(frame),
        "interval_hours": hours,
        "first_funding_time": int(frame.funding_time.iloc[0]),
        "last_funding_time": int(frame.funding_time.iloc[-1]),
        "mean_bps": float(bps.mean()),
        "median_bps": float(np.median(bps)),
        "std_bps": float(bps.std(ddof=1)) if len(bps) > 1 else None,
        "min_bps": float(bps.min()),
        "max_bps": float(bps.max()),
        "quantiles_bps": {
            str(q): float(np.quantile(bps, q)) for q in (0.01, 0.05, 0.25, 0.75, 0.95, 0.99)
        },
        "positive_fraction": float((rates > 0).mean()),
        "negative_fraction": float((rates < 0).mean()),
        "zero_fraction": float((rates == 0).mean()),
        "sum_settlement_rates_pct": float(rates.sum() * 100),
        "sum_caveat": "simple sum on fixed notional; excludes price P&L, costs and compounding",
        "positive_runs": positive_runs(rates),
        "stationarity": stationarity(rates, config),
    }
    lags = min(config.max_lags, len(rates) // 2 - 1)
    if lags < 1 or np.ptp(rates) == 0:
        result["correlations"] = {"status": "unavailable", "reason": "short or constant series"}
    else:
        ac, ac_interval = acf(
            rates, nlags=lags, fft=False, adjusted=False, alpha=config.alpha, missing="raise"
        )
        pc, pc_interval = pacf(rates, nlags=lags, method="ywm", alpha=config.alpha)
        result["correlations"] = {
            "status": "evaluated",
            "lags": list(range(lags + 1)),
            "lag_hours": [i * hours for i in range(lags + 1)],
            "acf": ac.tolist(),
            "pacf": pc.tolist(),
            "acf_confidence_interval": ac_interval.tolist(),
            "pacf_confidence_interval": pc_interval.tolist(),
            "alpha": config.alpha,
            "acf_method": "unadjusted, direct, Bartlett intervals",
            "pacf_method": "ywm",
            "caveat": "exploratory intervals; multiple lags/windows are not corrected",
        }
    return result


def describe_window(
    frame: pd.DataFrame,
    start: dt.date,
    end: dt.date,
    *,
    config: Config | None = None,
) -> dict:
    """Inspect [start, end); ignore future values before validation or statistics."""
    config = config or Config()
    selected = frame[
        (frame.funding_time >= funding_series.utc_ms(start))
        & (frame.funding_time < funding_series.utc_ms(end))
    ].copy()
    funding_series.validate(selected, start, end)
    # Never compute settlement-lag correlations across a change in interval length.
    blocks = selected.funding_interval_hours.ne(selected.funding_interval_hours.shift()).cumsum()
    return {
        "start": str(start),
        "end_exclusive": str(end),
        "rows": len(selected),
        "segments": [
            describe_segment(rows, config) for _, rows in selected.groupby(blocks, sort=True)
        ],
        "cadence_policy": "separate contiguous constant-cadence segments; no resampling or pooling",
    }


def analyze(
    frame: pd.DataFrame,
    *,
    warmup_start: dt.date,
    study_start: dt.date,
    study_end: dt.date,
    config: Config | None = None,
) -> dict:
    """Full-period EDA plus strictly prior monthly 90-day diagnostics; end is exclusive."""
    config = config or Config()
    if not warmup_start < study_start < study_end:
        raise ValueError("invalid study/warmup boundaries")
    funding_series.validate(frame, warmup_start, study_end)
    windows = {
        "warmup": describe_window(frame, warmup_start, study_start, config=config),
        "study": describe_window(frame, study_start, study_end, config=config),
    }
    rolling = []
    for cutoff in months_between(study_start, study_end - dt.timedelta(days=1)):
        if cutoff < study_start:
            continue
        start = cutoff - dt.timedelta(days=config.rolling_days)
        if start < warmup_start:
            raise ValueError("warmup does not cover the requested prior rolling window")
        rolling.append(
            {"cutoff": str(cutoff), **describe_window(frame, start, cutoff, config=config)}
        )
    return {
        "symbol": str(frame.symbol.iloc[0]),
        "windows": windows,
        "prior_monthly_windows": rolling,
        "scope": "descriptive EDA; study-wide statistics are not causal features or tuned rules",
    }
