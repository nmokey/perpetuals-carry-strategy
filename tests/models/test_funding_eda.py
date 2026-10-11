"""M6-T1 acceptance: exact statistics, cadence-aware lags, stationarity and causal windows."""

import datetime as dt
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from perpcarry.ingestion.funding_series import utc_ms
from perpcarry.models import funding_eda as eda


def test_acf_matches_hand_computed_covariance_and_lag_units(funding_frame_factory):
    frame = funding_frame_factory("2025-07-01", "2025-07-04")
    rates = np.array([1, -2, 4, 1, 0, 3, -1, 2, 5], dtype=float) * 0.00001
    frame["funding_rate"] = rates
    segment = eda.describe_segment(frame, eda.Config(max_lags=3))
    centered = rates - rates.mean()
    expected = [
        float(np.dot(centered[k:], centered[: len(centered) - k]) / np.dot(centered, centered))
        for k in range(4)
    ]
    np.testing.assert_allclose(segment["correlations"]["acf"], expected, rtol=0, atol=2e-16)
    assert segment["correlations"]["lag_hours"] == [0, 8, 16, 24]
    assert segment["mean_bps"] == float((rates * 10_000).mean())
    assert segment["sum_settlement_rates_pct"] == float(rates.sum() * 100)
    assert segment["negative_fraction"] == 2 / 9


def test_pacf_and_acf_on_a_known_ar1(funding_frame_factory):
    frame = funding_frame_factory("2025-01-01", "2027-01-01")
    rng = np.random.default_rng(2026)
    rates = np.zeros(len(frame))
    for i in range(1, len(rates)):
        rates[i] = 0.8 * rates[i - 1] + rng.normal(0, 0.00001)
    frame["funding_rate"] = rates
    c = eda.describe_segment(frame, eda.Config(max_lags=4))["correlations"]
    assert abs(c["acf"][1] - 0.8) < 0.04
    assert abs(c["pacf"][1] - 0.8) < 0.04
    assert max(abs(value) for value in c["pacf"][2:]) < 0.05
    assert c["pacf_method"] == "ywm"


def test_cadence_changes_are_segmented_using_later_row_interval():
    hours = np.array([0, 8, 16, 24, 32, 40, 44, 48, 52, 56, 60, 64, 68])
    times = utc_ms(dt.date(2025, 7, 1)) + hours * 3_600_000 + 137
    frame = pd.DataFrame(
        {
            "funding_time": times,
            "symbol": "TESTUSDT",
            "funding_rate": np.arange(len(times)) * 0.00001,
            "funding_interval_hours": [8] * 6 + [4] * 7,
            "date": pd.to_datetime(times, unit="ms", utc=True).strftime("%Y-%m-%d"),
        }
    )
    result = eda.describe_window(frame, dt.date(2025, 7, 1), dt.date(2025, 7, 4))
    assert [s["rows"] for s in result["segments"]] == [6, 7]
    assert [s["correlations"]["lag_hours"] for s in result["segments"]] == [[0, 8, 16], [0, 4, 8]]


def test_stationarity_distinguishes_iid_from_random_walk():
    rng = np.random.default_rng(1729)
    stationary = eda.stationarity(rng.normal(size=1024), eda.Config())
    random_walk = eda.stationarity(np.cumsum(rng.normal(size=1024)), eda.Config())
    assert stationary["interpretation"] == "compatible_with_level_stationarity"
    assert random_walk["interpretation"] == "evidence_against_level_stationarity"
    assert stationary["adf"]["null"] == "unit_root"
    assert stationary["kpss"]["null"] == "level_stationary"
    assert stationary["kpss"]["pvalue_bound"] == "above_table"
    assert random_walk["kpss"]["pvalue_bound"] == "below_table"


@pytest.mark.parametrize(
    "adf_p,kpss_p,expected",
    [
        (0.01, 0.1, "compatible_with_level_stationarity"),
        (0.3, 0.01, "evidence_against_level_stationarity"),
        (0.01, 0.01, "mixed_possible_breaks_or_misspecification"),
        (0.3, 0.1, "inconclusive"),
    ],
)
def test_opposing_nulls_do_not_become_false_stationarity_claims(
    monkeypatch, adf_p, kpss_p, expected
):
    monkeypatch.setattr(eda, "adfuller", lambda *a, **k: (-2.0, adf_p, 3, 60, {"5%": -2.9}))
    monkeypatch.setattr(eda, "kpss", lambda *a, **k: (0.7, kpss_p, 4, {"5%": 0.46}))
    result = eda.stationarity(np.arange(64, dtype=float), eda.Config())
    assert result["interpretation"] == expected
    assert result["adf"]["reject_null"] is (adf_p < 0.05)
    assert result["kpss"]["reject_null"] is (kpss_p < 0.05)


def test_constant_and_short_series_are_explicitly_unavailable(funding_frame_factory):
    frame = funding_frame_factory("2025-07-01", "2025-07-02")
    segment = eda.describe_segment(frame, eda.Config())
    assert segment["stationarity"]["status"] == "unavailable"
    assert segment["correlations"]["status"] == "unavailable"
    frame["funding_rate"] = 0.00001
    segment = eda.describe_segment(frame, eda.Config())
    assert segment["correlations"]["status"] == "unavailable"
    assert "acf" not in segment["correlations"]


def test_positive_runs_break_on_zero_and_preserve_boundary_censoring():
    result = eda.positive_runs(np.array([1, 1, 0, 1, -1, 1, 1, 1]))
    assert result["count"] == 3
    assert result["max_settlements"] == 3
    assert result["median_settlements"] == 2
    assert result["left_boundary_positive"] and result["right_boundary_positive"]
    assert eda.positive_runs(np.array([-1, 0]))["max_settlements"] == 0


def test_prior_window_is_unchanged_by_corrupt_future_and_cutoff_is_exclusive(funding_frame_factory):
    frame = funding_frame_factory()
    start, cutoff = dt.date(2025, 8, 2), dt.date(2025, 9, 1)
    original = eda.describe_window(frame, start, cutoff)
    future = frame.funding_time >= utc_ms(cutoff)
    frame.loc[future, "funding_rate"] = float("nan")
    # A settlement exactly at cutoff must also remain excluded.
    frame.loc[frame.index[future][0], "funding_time"] = utc_ms(cutoff)
    changed = eda.describe_window(frame, start, cutoff)
    assert original == changed
    assert changed["rows"] == 90
    assert changed["segments"][0]["last_funding_time"] < utc_ms(cutoff)


def test_monthly_windows_are_prior_and_deterministic(funding_frame_factory):
    frame = funding_frame_factory()
    args = dict(
        warmup_start=dt.date(2025, 7, 1),
        study_start=dt.date(2025, 9, 1),
        study_end=dt.date(2025, 10, 3),
        config=eda.Config(rolling_days=30),
    )
    original = eda.analyze(frame, **args)
    assert original == eda.analyze(frame.copy(), **args)
    windows = original["prior_monthly_windows"]
    assert [w["cutoff"] for w in windows] == ["2025-09-01", "2025-10-01"]
    assert all(w["rows"] == 90 and w["end_exclusive"] == w["cutoff"] for w in windows)
    frame.loc[frame.funding_time >= utc_ms(dt.date(2025, 9, 1)), "funding_rate"] *= -2
    changed = eda.analyze(frame, **args)
    assert original["prior_monthly_windows"][0] == changed["prior_monthly_windows"][0]
    assert original["windows"]["study"] != changed["windows"]["study"]
    with pytest.raises(ValueError, match="warmup"):
        eda.analyze(frame, **{**args, "config": replace(args["config"], rolling_days=120)})
