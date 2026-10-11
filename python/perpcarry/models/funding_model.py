"""M6-T2: conjugate Gaussian AR(1), with explicit units and unrestricted persistence."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.stats import invgamma, t


@dataclass(frozen=True)
class Prior:
    mean: tuple[float, float] = (0.0, 0.0)
    precision: tuple[tuple[float, float], tuple[float, float]] = ((1.0, 0.0), (0.0, 1.0))
    shape: float = 3.0
    scale: float = 2.0

    def __post_init__(self):
        mean, precision = np.asarray(self.mean), np.asarray(self.precision)
        if mean.shape != (2,) or precision.shape != (2, 2):
            raise ValueError("prior requires two coefficients and a 2x2 precision")
        if not np.isfinite(mean).all() or not np.isfinite(precision).all():
            raise ValueError("prior parameters must be finite")
        if not np.array_equal(precision, precision.T):
            raise ValueError("prior precision must be symmetric")
        if np.linalg.eigvalsh(precision).min() <= 0:
            raise ValueError("prior precision must be positive definite")
        if not np.isfinite([self.shape, self.scale]).all() or min(self.shape, self.scale) <= 0:
            raise ValueError("inverse-gamma shape and scale must be positive and finite")


def validate_rates(values):
    values = np.asarray(values, dtype=float)
    if values.ndim != 1 or not len(values) or not np.isfinite(values).all():
        raise ValueError("rates must be a nonempty finite one-dimensional array")
    return values


@dataclass(frozen=True)
class Posterior:
    mean: tuple[float, float]
    covariance_factor: tuple[tuple[float, float], tuple[float, float]]
    shape: float
    scale: float
    observations: int
    interval_hours: int

    def predict(self, previous_rates):
        """Marginal one-step Student-t parameters, location/scale in settlement fractions."""
        previous = validate_rates(previous_rates) * 10_000
        design = np.column_stack((np.ones(len(previous)), previous))
        location = design @ np.asarray(self.mean)
        leverage = np.einsum("ij,jk,ik->i", design, self.covariance_factor, design)
        scale = np.sqrt(self.scale / self.shape * (1.0 + leverage))
        return 2 * self.shape, location / 10_000, scale / 10_000

    def sample(self, size: int, *, seed: int):
        """Joint posterior draws: coefficients in bps/dimensionless, variance in bps²."""
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            raise ValueError("positive integer sample size required")
        rng = np.random.default_rng(seed)
        variance = invgamma.rvs(self.shape, scale=self.scale, size=size, random_state=rng)
        noise = rng.standard_normal((size, 2)) @ np.linalg.cholesky(self.covariance_factor).T
        coefficients = np.asarray(self.mean) + noise * np.sqrt(variance[:, None])
        return coefficients, variance

    def summary(self, level: float = 0.95):
        if not 0 < level < 1:
            raise ValueError("credible level must be inside (0,1)")
        q = [(1 - level) / 2, (1 + level) / 2]
        factors = np.asarray(self.covariance_factor)
        scales = np.sqrt(self.scale / self.shape * np.diag(factors))
        intervals = np.asarray(self.mean)[:, None] + scales[:, None] * t.ppf(q, 2 * self.shape)
        phi_scale = scales[1]
        stationary_mass = t.cdf(1, 2 * self.shape, loc=self.mean[1], scale=phi_scale) - t.cdf(
            -1, 2 * self.shape, loc=self.mean[1], scale=phi_scale
        )
        return {
            "observations": self.observations,
            "interval_hours": self.interval_hours,
            "credible_level": level,
            "intercept_bps": {"mean": self.mean[0], "interval": intervals[0].tolist()},
            "phi": {"mean": self.mean[1], "interval": intervals[1].tolist()},
            "innovation_variance_bps2": {
                "mean": self.scale / (self.shape - 1) if self.shape > 1 else None,
                "interval": invgamma.ppf(q, self.shape, scale=self.scale).tolist(),
            },
            "nonstationary_phi_probability": float(1 - stationary_mass),
            "shape": self.shape,
            "scale_bps2": self.scale,
            "covariance_factor": factors.tolist(),
        }


def fit(rates, *, interval_hours: int, prior: Prior | None = None) -> Posterior:
    """Condition on first settlement; caller owns time/cadence validation and cutoff selection."""
    prior = prior or Prior()
    if (
        isinstance(interval_hours, bool)
        or not isinstance(interval_hours, int)
        or not 1 <= interval_hours <= 24
    ):
        raise ValueError("integer settlement cadence in [1,24] hours required")
    bps = validate_rates(rates) * 10_000
    if len(bps) < 3:
        raise ValueError("at least three settlements required")
    design = np.column_stack((np.ones(len(bps) - 1), bps[:-1]))
    target = bps[1:]
    precision = np.asarray(prior.precision) + design.T @ design
    mean = np.linalg.solve(precision, np.asarray(prior.precision) @ prior.mean + design.T @ target)
    residual = target - design @ mean
    displacement = mean - prior.mean
    scale = prior.scale + 0.5 * (
        residual @ residual + displacement @ np.asarray(prior.precision) @ displacement
    )
    factor = np.linalg.solve(precision, np.eye(2))
    if not np.isfinite(mean).all() or not np.isfinite(factor).all() or not np.isfinite(scale):
        raise ValueError("nonfinite posterior; input scale exceeds numerical range")
    return Posterior(
        tuple(mean.tolist()),
        tuple(map(tuple, factor.tolist())),
        prior.shape + len(target) / 2,
        float(scale),
        len(target),
        interval_hours,
    )
