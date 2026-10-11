"""M6-T2 diagnostic checks; no strategy decisions or optimized acceptance threshold."""

from __future__ import annotations

import numpy as np
from scipy.stats import t
from statsmodels.tsa.stattools import acf

from perpcarry.models.funding_model import Posterior, validate_rates


def _statistics(residual):
    return np.array(
        [
            np.std(residual, ddof=1),
            np.min(residual),
            acf(residual, nlags=1, fft=False)[1] if np.ptp(residual) else 0.0,
        ]
    )


def check(model: Posterior, previous_rates, observed_rates) -> dict:
    previous, observed = validate_rates(previous_rates), validate_rates(observed_rates)
    if len(previous) != len(observed) or len(observed) < 3:
        raise ValueError("at least three matched previous/observed pairs required")
    df, location, scale = model.predict(previous)
    residual = (observed - location) * 10_000
    standardized = (observed - location) / scale
    pit = t.cdf(observed, df, loc=location, scale=scale)
    return {
        "rows": len(observed),
        "coverage": {
            str(level): float(np.mean(np.abs(standardized) <= t.ppf((1 + level) / 2, df)))
            for level in (0.5, 0.8, 0.95, 0.99)
        },
        "mean_log_predictive_density_fraction_units": float(
            np.mean(t.logpdf(observed, df, loc=location, scale=scale))
        ),
        "residual_statistics": dict(
            zip(("std_bps", "minimum_bps", "lag1_acf"), _statistics(residual).tolist(), strict=True)
        ),
        "residual_acf": acf(residual, nlags=min(12, len(residual) - 1), fft=False).tolist()
        if np.ptp(residual)
        else None,
        "pit_bin_edges": np.linspace(0, 1, 11).tolist(),
        "pit_counts": np.histogram(pit, bins=np.linspace(0, 1, 11))[0].tolist(),
        "negative_tail": {
            str(bps): {
                "observed_count": int(np.sum(observed < bps / 10_000)),
                "expected_count": float(np.sum(t.cdf(bps / 10_000, df, loc=location, scale=scale))),
            }
            for bps in (-1, -5, -10)
        },
        "caveat": (
            "one-step conditional diagnostics; correlated observations, "
            "exploratory checks; no profitability implication"
        ),
    }


def replicate(model: Posterior, rates, *, draws: int = 2000, seed: int = 602) -> dict:
    """In-sample conditional PPC at fixed observed lags, using shared joint posterior draws."""
    bps = validate_rates(rates) * 10_000
    if len(bps) < 4:
        raise ValueError("at least four settlements for replication")
    coefficients, variance = model.sample(draws, seed=seed)
    design = np.column_stack((np.ones(len(bps) - 1), bps[:-1]))
    simulated = coefficients @ design.T + np.random.default_rng(seed + 1).standard_normal(
        (draws, len(bps) - 1)
    ) * np.sqrt(variance[:, None])
    location = design @ model.mean
    observed = _statistics(bps[1:] - location)
    statistics = np.array([_statistics(row - location) for row in simulated])
    return {
        "draws": draws,
        "seed": seed,
        "scope": (
            "in-sample conditional replication with observed lag inputs; "
            "not independent validation or open-loop paths"
        ),
        "statistics": {
            name: {
                "observed": float(observed[i]),
                "replicated_95_interval": np.quantile(statistics[:, i], [0.025, 0.975]).tolist(),
                "replicated_fraction_below_observed": float(
                    np.mean(statistics[:, i] <= observed[i])
                ),
            }
            for i, name in enumerate(
                ("residual_std_bps", "minimum_residual_bps", "residual_lag1_acf")
            )
        },
    }
