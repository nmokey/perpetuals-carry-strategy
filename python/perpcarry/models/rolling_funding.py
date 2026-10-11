"""M6-T3: causal settlement updates and recursive posterior predictive funding paths."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np

from perpcarry.models.funding_model import Posterior, Prior, fit

DAY_MS = 86_400_000
HOUR_MS = 3_600_000
JITTER_MS = 5000


class FundingHistoryError(ValueError):
    """Invalid observation or decision time; the current state remains intact."""


class FundingModelUnavailable(ValueError):
    """Observed history is too short or stale for a forecast."""


def _integer(value, name, minimum=1):
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < minimum:
        raise FundingHistoryError(f"{name} must be an integer >= {minimum}")
    return int(value)


@dataclass(frozen=True)
class CumulativeFundingForecast:
    samples: tuple[float, ...]
    horizon_settlements: int
    interval_hours: int
    as_of: int
    last_observation_time: int
    training_first_time: int
    training_settlements: int
    seed: int

    def probability_above(self, fraction: float) -> float:
        if not np.isfinite(fraction):
            raise ValueError("threshold must be a finite funding fraction")
        return float(np.mean(np.asarray(self.samples) > fraction))

    def summary(self) -> dict:
        values = np.asarray(self.samples)
        probability = self.probability_above(0.0)
        return {
            "horizon_settlements": self.horizon_settlements,
            "interval_hours": self.interval_hours,
            "as_of": self.as_of,
            "last_observation_time": self.last_observation_time,
            "training_first_time": self.training_first_time,
            "training_settlements": self.training_settlements,
            "seed": self.seed,
            "draws": len(values),
            "mean_fraction": float(values.mean()),
            "median_fraction": float(np.median(values)),
            "interval_95_fraction": np.quantile(values, [0.025, 0.975]).tolist(),
            "positive_probability": probability,
            "positive_probability_mc_standard_error": float(
                np.sqrt(probability * (1 - probability) / len(values))
            ),
            "scope": "fixed-notional settlement sum; excludes price P&L, costs and compounding",
        }


class RollingFundingModel:
    """One symbol's observed history. Update availability is the caller's responsibility."""

    def __init__(self, *, rolling_days=90, min_settlements=30, prior: Prior | None = None):
        self.rolling_days = _integer(rolling_days, "rolling_days")
        self.min_settlements = _integer(min_settlements, "min_settlements", 3)
        self.prior = prior or Prior()
        self._history = deque()
        self.cadence_resets = 0

    def update(self, funding_time: int, funding_rate: float, interval_hours: int) -> None:
        timestamp = _integer(funding_time, "funding_time", 0)
        hours = _integer(interval_hours, "interval_hours")
        if hours > 24 or not np.isfinite(funding_rate) or abs(funding_rate) > 0.05:
            raise FundingHistoryError("invalid cadence or funding fraction outside sanity bound")
        if self._history:
            previous_time, _, previous_hours = self._history[-1]
            if timestamp <= previous_time:
                raise FundingHistoryError("funding times must be strictly increasing")
            if abs(timestamp - previous_time - hours * HOUR_MS) > JITTER_MS:
                raise FundingHistoryError("missing or irregular funding settlement")
            if hours != previous_hours:
                self._history.clear()
                self.cadence_resets += 1
        self._history.append((timestamp, float(funding_rate), hours))
        cutoff = timestamp - self.rolling_days * DAY_MS
        while self._history[0][0] < cutoff:
            self._history.popleft()

    def _selection(self, as_of):
        if not self._history:
            raise FundingModelUnavailable("no observed funding history")
        latest, _, hours = self._history[-1]
        decision = latest if as_of is None else _integer(as_of, "as_of", 0)
        if decision < latest:
            raise FundingHistoryError("as_of precedes an already admitted observation")
        if decision - latest > hours * HOUR_MS + JITTER_MS:
            raise FundingModelUnavailable("stale funding history")
        cutoff = decision - self.rolling_days * DAY_MS
        selected = [row for row in self._history if row[0] >= cutoff]
        if len(selected) < self.min_settlements:
            raise FundingModelUnavailable("insufficient current-cadence rolling history")
        return decision, selected

    def posterior(self, *, as_of: int | None = None) -> Posterior:
        _, selected = self._selection(as_of)
        return fit([row[1] for row in selected], interval_hours=selected[-1][2], prior=self.prior)

    def training_summary(self, *, as_of: int | None = None) -> dict:
        decision, selected = self._selection(as_of)
        return {
            "as_of": decision,
            "training_first_time": selected[0][0],
            "last_observation_time": selected[-1][0],
            "training_settlements": len(selected),
            "interval_hours": selected[-1][2],
            "cadence_resets": self.cadence_resets,
            "last_funding_rate": selected[-1][1],
        }

    def predict_cumulative_funding(
        self, horizon: int, *, as_of: int | None = None, draws: int = 4096, seed: int = 603
    ) -> CumulativeFundingForecast:
        horizon = _integer(horizon, "horizon")
        draws = _integer(draws, "draws", 2)
        seed = _integer(seed, "seed", 0)
        decision, selected = self._selection(as_of)
        posterior = self.posterior(as_of=decision)
        coefficients, variance = posterior.sample(draws, seed=seed)
        rng = np.random.default_rng(seed + 1)
        current = np.full(draws, selected[-1][1] * 10_000)
        total = np.zeros(draws)
        with np.errstate(over="ignore", invalid="ignore"):
            for _ in range(horizon):
                current = (
                    coefficients[:, 0]
                    + coefficients[:, 1] * current
                    + rng.standard_normal(draws) * np.sqrt(variance)
                )
                total += current
        if not np.isfinite(total).all():
            raise FundingModelUnavailable("nonfinite predictive paths; horizon/model unstable")
        return CumulativeFundingForecast(
            tuple((total / 10_000).tolist()),
            horizon,
            selected[-1][2],
            decision,
            selected[-1][0],
            selected[0][0],
            len(selected),
            seed,
        )
