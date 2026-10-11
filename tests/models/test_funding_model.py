"""M6-T2: independent posterior algebra, parameter recovery and predictive checks."""

import json
from dataclasses import asdict

import numpy as np
import pytest
from scipy.stats import invgamma, t

from perpcarry.models import funding_checks
from perpcarry.models.funding_model import Prior, fit


def synthetic(n=3000, *, seed=21, intercept=0.12, phi=0.7, sigma=0.4):
    rng = np.random.default_rng(seed)
    values = np.zeros(n)
    for i in range(1, n):
        values[i] = intercept + phi * values[i - 1] + rng.normal(0, sigma)
    return values / 10_000


def test_independent_posterior_algebra_and_fraction_units():
    bps = np.array([0.3, -0.8, 1.1, 0.4, -0.1])
    prior = Prior(mean=(0.2, 0.4), precision=((2.0, 0.3), (0.3, 1.5)), shape=2.2, scale=0.7)
    model = fit(bps / 10_000, interval_hours=8, prior=prior)
    x = np.column_stack((np.ones(4), bps[:-1]))
    precision = np.array(prior.precision) + x.T @ x
    factor = np.linalg.inv(precision)
    mean = factor @ (np.array(prior.precision) @ prior.mean + x.T @ bps[1:])
    scale = prior.scale + 0.5 * (
        bps[1:] @ bps[1:]
        + np.array(prior.mean) @ prior.precision @ prior.mean
        - mean @ precision @ mean
    )
    np.testing.assert_allclose(model.mean, mean, rtol=0, atol=2e-16)
    np.testing.assert_allclose(model.covariance_factor, factor, rtol=0, atol=1e-16)
    assert model.shape == prior.shape + 2
    assert model.scale == pytest.approx(scale, abs=4e-16, rel=0)
    assert model.observations == 4
    inputs = np.array([-0.7, 0.2, 2.1])
    design = np.column_stack((np.ones(3), inputs))
    df, loc, pred_scale = model.predict(inputs / 10_000)
    assert df == 2 * model.shape
    np.testing.assert_allclose(loc, design @ mean / 10_000, atol=1e-20, rtol=0)
    expected_scale = (
        np.sqrt(scale / model.shape * (1 + np.diag(design @ factor @ design.T))) / 10_000
    )
    np.testing.assert_allclose(pred_scale, expected_scale, atol=1e-20, rtol=0)
    summary = model.summary()
    np.testing.assert_allclose(
        summary["innovation_variance_bps2"]["interval"],
        invgamma.ppf([0.025, 0.975], model.shape, scale=model.scale),
        rtol=0,
        atol=2e-15,
    )
    expected_phi = mean[1] + t.ppf([0.025, 0.975], df) * np.sqrt(scale / model.shape * factor[1, 1])
    np.testing.assert_allclose(summary["phi"]["interval"], expected_phi, rtol=0, atol=1e-15)


def test_recovers_true_parameters_and_gaussian_predictive_behavior():
    rates = synthetic()
    model = fit(rates, interval_hours=8)
    summary = model.summary()
    for name, truth in [("intercept_bps", 0.12), ("phi", 0.7), ("innovation_variance_bps2", 0.16)]:
        low, high = summary[name]["interval"]
        assert low < truth < high, (name, summary[name])
    checks = funding_checks.check(model, rates[:-1], rates[1:])
    assert 0.94 < checks["coverage"]["0.95"] < 0.96
    assert abs(checks["residual_statistics"]["lag1_acf"]) < 0.05
    replication = funding_checks.replicate(model, rates, draws=300)
    # Even a true model can put one extreme outside a 95% replication interval.
    # Do not select another seed to manufacture a clean minimum-tail check.
    for name in ("residual_std_bps", "residual_lag1_acf"):
        value = replication["statistics"][name]
        low, high = value["replicated_95_interval"]
        assert low < value["observed"] < high


def test_joint_samples_match_covariance_variance_and_prediction():
    model = fit(synthetic(50), interval_hours=8)
    coefficients, variance = model.sample(100_000, seed=26)
    again = model.sample(100_000, seed=26)
    np.testing.assert_array_equal(coefficients, again[0])
    np.testing.assert_array_equal(variance, again[1])
    expected_variance = model.scale / (model.shape - 1)
    assert variance.mean() == pytest.approx(expected_variance, rel=0.01)
    np.testing.assert_allclose(
        np.cov(coefficients.T),
        expected_variance * np.asarray(model.covariance_factor),
        rtol=0.025,
        atol=1e-5,
    )
    # Whiten conditional draws: variance must scale BOTH coefficients in the same draw.
    white = (
        (coefficients - model.mean)
        @ np.linalg.inv(np.linalg.cholesky(model.covariance_factor)).T
        / np.sqrt(variance[:, None])
    )
    np.testing.assert_allclose(np.cov(white.T), np.eye(2), atol=0.015, rtol=0)
    rng = np.random.default_rng(40)
    previous = 0.6
    simulated = (
        coefficients[:, 0]
        + coefficients[:, 1] * previous
        + rng.normal(size=len(variance)) * np.sqrt(variance)
    )
    df, loc, scale = model.predict([previous / 10_000])
    assert simulated.var() == pytest.approx(float(scale[0] ** 2 * 1e8 * df / (df - 2)), rel=0.025)


@pytest.mark.parametrize("rates", [[], [0, 1], [np.nan, 0, 1], [0, np.inf, 1], [[0, 1, 2]]])
def test_invalid_rates_rejected(rates):
    with pytest.raises(ValueError):
        fit(rates, interval_hours=8)


@pytest.mark.parametrize("hours", [0, 25, 8.0, True])
def test_invalid_cadence_rejected(hours):
    with pytest.raises(ValueError, match="cadence"):
        fit([0, 0.0001, 0], interval_hours=hours)


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(shape=0),
        dict(scale=np.inf),
        dict(mean=(0, np.nan)),
        dict(precision=((1, 2), (0, 1))),
        dict(precision=((1, 2), (2, 1))),
        dict(mean=(0,)),
    ],
)
def test_invalid_prior_rejected(kwargs):
    with pytest.raises(ValueError):
        Prior(**kwargs)


def test_constant_input_proper_prior_and_unrestricted_explosive_phi():
    constant = fit(np.full(50, 0.0001), interval_hours=4)
    assert np.isfinite(constant.predict([0.0001])[2]).all()
    # Exact linear growth distinguishes a true unconstrained estimate from clipping.
    explosive = fit((1.05 ** np.arange(100)) / 10_000, interval_hours=8)
    assert explosive.mean[1] > 1
    assert explosive.summary()["nonstationary_phi_probability"] > 0.999


def test_diagnostics_deterministic_tail_and_invalid_inputs():
    rates = synthetic(300)
    model = fit(rates[:100], interval_hours=8)
    replication = funding_checks.replicate(model, rates[:100], draws=100)
    assert replication == funding_checks.replicate(model, rates[:100], draws=100)
    assert "not independent" in replication["scope"]
    rates[-1] = -0.003
    check = funding_checks.check(model, rates[99:-1], rates[100:])
    assert check["negative_tail"]["-10"]["observed_count"] == 1
    assert check["negative_tail"]["-10"]["expected_count"] < 0.001
    assert sum(check["pit_counts"]) == 200
    for previous, observed in [([0], [0]), ([0, 1, 2], [0, 1]), ([0, np.nan, 1], [0, 1, 2])]:
        with pytest.raises(ValueError):
            funding_checks.check(model, previous, observed)
    for invalid in [0, 1.2, True]:
        with pytest.raises(ValueError):
            model.sample(invalid, seed=1)
    with pytest.raises(ValueError):
        model.summary(1)
    assert json.loads(json.dumps(asdict(model), allow_nan=False))["observations"] == 99


def test_replication_includes_innovation_noise_and_shared_parameters():
    rates = np.full(40, 0.0001)
    model = fit(rates, interval_hours=8)
    replication = funding_checks.replicate(model, rates, draws=300)
    low, high = replication["statistics"]["residual_std_bps"]["replicated_95_interval"]
    assert low > 0.2 and high < 0.5
    # Without innovation noise, fixed lag inputs give a constant replicate (zero std).
    assert replication["statistics"]["residual_std_bps"]["observed"] < 1e-15
