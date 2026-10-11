"""M6-T3: forecast before observation, then score in a separate retrospective pass."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd
from scipy.stats import t
from statsmodels.tsa.stattools import acf

from perpcarry.ingestion.funding_series import utc_ms
from perpcarry.models.funding_model import Prior
from perpcarry.models.rolling_funding import FundingModelUnavailable, RollingFundingModel


@dataclass(frozen=True)
class Config:
    rolling_days: int = 90
    min_settlements: int = 30
    horizons: tuple[int, ...] = (3, 21)
    draws: int = 4096
    seed: int = 603

    def __post_init__(self):
        RollingFundingModel(rolling_days=self.rolling_days, min_settlements=self.min_settlements)
        integers = (self.draws, self.seed, *self.horizons)
        if any(isinstance(x, bool) or not isinstance(x, int) for x in integers):
            raise ValueError("integer draws, seed and horizons required")
        if self.draws < 2 or self.seed < 0 or any(h < 1 for h in self.horizons):
            raise ValueError("positive horizons, at least two draws and nonnegative seed required")
        if len(set(self.horizons)) != len(self.horizons):
            raise ValueError("duplicate diagnostic horizons")


def prior_spec(prior: Prior) -> dict:
    """Explicit JSON-compatible prior metadata, preserving original numeric values."""
    return {
        "mean": list(prior.mean),
        "precision": [list(row) for row in prior.precision],
        "shape": prior.shape,
        "scale": prior.scale,
    }


def forecast_stream(
    frame: pd.DataFrame,
    *,
    study_start: dt.date,
    study_end: dt.date,
    config: Config | None = None,
    prior: Prior | None = None,
):
    """Yield forecasts WITHOUT looking at current/future funding values. End is exclusive.

    Input must be chronological, one-symbol, admitted observations. Validate each rate only
    when observed; shuffling or corrupting a future suffix cannot poison earlier forecasts.
    """
    config = config or Config()
    model = RollingFundingModel(
        rolling_days=config.rolling_days, min_settlements=config.min_settlements, prior=prior
    )
    start, end = utc_ms(study_start), utc_ms(study_end)
    if start >= end:
        raise ValueError("invalid study boundaries")
    frozen = None
    symbol = None
    for row in frame.itertuples(index=False):
        timestamp = row.funding_time
        if timestamp >= end:
            break
        if symbol is None:
            symbol = row.symbol
        if row.symbol != symbol:
            raise ValueError("one symbol per funding forecast stream")
        if timestamp >= start:
            record = {"funding_time": timestamp}
            try:
                posterior = model.posterior(as_of=timestamp)
                training = model.training_summary(as_of=timestamp)
                previous_rate = training["last_funding_rate"]
                df, location, scale = posterior.predict([previous_rate])
                if frozen is None or frozen.interval_hours != posterior.interval_hours:
                    frozen = posterior
                frozen_df, frozen_location, frozen_scale = frozen.predict([previous_rate])
                record.update(
                    status="forecast",
                    training=training,
                    posterior=posterior.summary(),
                    one_step={
                        "df": df,
                        "location_fraction": float(location[0]),
                        "scale_fraction": float(scale[0]),
                    },
                    frozen_one_step={
                        "df": frozen_df,
                        "location_fraction": float(frozen_location[0]),
                        "scale_fraction": float(frozen_scale[0]),
                    },
                    cumulative={
                        str(h): model.predict_cumulative_funding(
                            h, as_of=timestamp, draws=config.draws, seed=config.seed
                        ).summary()
                        for h in config.horizons
                    },
                )
            except FundingModelUnavailable as error:
                record.update(status="unavailable", reason=str(error))
            yield record
        # This happens only AFTER the forecast is yielded; no validation inspects future rates.
        model.update(timestamp, row.funding_rate, row.funding_interval_hours)


def score_one_step(records: list[dict], observations: pd.DataFrame, *, key="one_step") -> dict:
    lookup = observations.set_index("funding_time")
    selected = [
        r
        for r in records
        if r["status"] == "forecast"
        and r["training"]["interval_hours"]
        == int(lookup.loc[r["funding_time"], "funding_interval_hours"])
    ]
    if not selected:
        return {"rows": 0, "reason": "no matching-cadence forecasts"}
    observed = np.array([lookup.loc[r["funding_time"], "funding_rate"] for r in selected])
    df, location, scale = np.array(
        [[r[key]["df"], r[key]["location_fraction"], r[key]["scale_fraction"]] for r in selected]
    ).T
    z = (observed - location) / scale
    residual = observed - location
    positive = t.sf(0, df, loc=location, scale=scale)
    pit = t.cdf(observed, df, loc=location, scale=scale)
    return {
        "rows": len(selected),
        "cadence_excluded": sum(r["status"] == "forecast" for r in records) - len(selected),
        "coverage": {
            str(level): float(np.mean(np.abs(z) <= t.ppf((1 + level) / 2, df)))
            for level in (0.5, 0.8, 0.95, 0.99)
        },
        "lower_95_misses": int(np.sum(z < t.ppf(0.025, df))),
        "upper_95_misses": int(np.sum(z > t.ppf(0.975, df))),
        "positive_probability_brier": float(np.mean((positive - (observed > 0)) ** 2)),
        "mean_log_predictive_density_fraction_units": float(
            np.mean(t.logpdf(observed, df, loc=location, scale=scale))
        ),
        "pit_counts": np.histogram(pit, bins=np.linspace(0, 1, 11))[0].tolist(),
        "residual_acf": acf(residual, nlags=min(12, len(residual) - 1), fft=False).tolist()
        if np.ptp(residual)
        else None,
        "negative_tail": {
            str(bps): {
                "observed_count": int(np.sum(observed < bps / 10_000)),
                "expected_count": float(np.sum(t.cdf(bps / 10_000, df, loc=location, scale=scale))),
            }
            for bps in (-1, -5, -10)
        },
    }


def score_cumulative(records: list[dict], observations: pd.DataFrame, horizon: int) -> dict:
    lookup = {int(value): i for i, value in enumerate(observations.funding_time)}
    rates = observations.funding_rate.to_numpy()
    hours = observations.funding_interval_hours.to_numpy()
    actual, low, high, positive = [], [], [], []
    incomplete = cadence_excluded = unavailable = 0
    for record in records:
        if record["status"] != "forecast":
            unavailable += 1
            continue
        i = lookup[record["funding_time"]]
        forecast = record["cumulative"][str(horizon)]
        if i + horizon > len(rates):
            incomplete += 1
            continue
        if np.any(hours[i : i + horizon] != forecast["interval_hours"]):
            cadence_excluded += 1
            continue
        actual.append(float(rates[i : i + horizon].sum()))
        interval = forecast["interval_95_fraction"]
        low.append(interval[0])
        high.append(interval[1])
        positive.append(forecast["positive_probability"])
    values = np.asarray(actual)
    result = {
        "horizon_settlements": horizon,
        "rows": len(values),
        "incomplete_endpoints": incomplete,
        "cadence_excluded": cadence_excluded,
        "unavailable": unavailable,
        "caveat": "overlapping conditional forecasts; dependent scores, diagnostic horizon only",
    }
    if len(values):
        result.update(
            coverage_95=float(np.mean((values >= low) & (values <= high))),
            lower_95_misses=int(np.sum(values < low)),
            upper_95_misses=int(np.sum(values > high)),
            positive_probability_brier=float(np.mean((np.asarray(positive) - (values > 0)) ** 2)),
        )
    return result


def analyze(frame, *, study_start, study_end, config: Config | None = None) -> dict:
    config = config or Config()
    records = list(
        forecast_stream(frame, study_start=study_start, study_end=study_end, config=config)
    )
    study = frame[
        (frame.funding_time >= utc_ms(study_start)) & (frame.funding_time < utc_ms(study_end))
    ]
    monthly = {}
    for month in sorted(
        {
            dt.datetime.fromtimestamp(r["funding_time"] / 1000, dt.UTC).strftime("%Y-%m")
            for r in records
        }
    ):
        subset = [
            r
            for r in records
            if dt.datetime.fromtimestamp(r["funding_time"] / 1000, dt.UTC).strftime("%Y-%m")
            == month
        ]
        monthly[month] = score_one_step(subset, study)
    sensitivity = {}
    variants = {
        "variance_scale_0.5": Prior(scale=0.5),
        "variance_scale_8": Prior(scale=8),
        "precision_0.25": Prior(precision=((0.25, 0.0), (0.0, 0.25))),
        "precision_4": Prior(precision=((4.0, 0.0), (0.0, 4.0))),
    }
    for name, prior in variants.items():
        predictions = list(
            forecast_stream(
                frame,
                study_start=study_start,
                study_end=study_end,
                config=replace(config, horizons=()),
                prior=prior,
            )
        )
        sensitivity[name] = {
            "prior": prior_spec(prior),
            "one_step": score_one_step(predictions, study),
        }
    return {
        "forecast_records": records,
        "rows": len(records),
        "unavailable": sum(r["status"] != "forecast" for r in records),
        "one_step": score_one_step(records, study),
        "frozen_comparator": score_one_step(records, study, key="frozen_one_step"),
        "cumulative": {str(h): score_cumulative(records, study, h) for h in config.horizons},
        "monthly": monthly,
        "prior_sensitivity": sensitivity,
        "scope": (
            "causal funding predictions and retrospective diagnostics; "
            "no strategy or tuned prior selection"
        ),
    }
