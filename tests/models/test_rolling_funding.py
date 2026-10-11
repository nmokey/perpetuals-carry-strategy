"""M6-T3: causal windows, regime changes, recursive predictive uncertainty and no look-ahead."""

import datetime as dt
from itertools import islice

import numpy as np
import pytest

from perpcarry.models.funding_model import fit
from perpcarry.models.funding_walk_forward import Config, forecast_stream, score_cumulative
from perpcarry.models.rolling_funding import (
    DAY_MS,
    HOUR_MS,
    FundingHistoryError,
    FundingModelUnavailable,
    RollingFundingModel,
)


def populated(*, days=2, n=20, hours=8):
    model = RollingFundingModel(rolling_days=days, min_settlements=3)
    times = np.arange(n) * hours * HOUR_MS + 137
    rates = np.random.default_rng(4).normal(0.2, 0.5, n) / 10_000
    for timestamp, rate in zip(times, rates, strict=True):
        model.update(timestamp, rate, hours)
    return model, times, rates


def test_window_boundaries_evict_old_pairs_and_match_independent_batch():
    model, times, rates = populated()
    at = int(times[-1])
    selected = rates[times >= at - 2 * DAY_MS]
    assert model.posterior(as_of=at) == fit(selected, interval_hours=8)
    state = model.training_summary(as_of=at)
    assert state["training_settlements"] == 7
    assert state["training_first_time"] == at - 2 * DAY_MS
    # One ms advances the lower boundary; that retained boundary row now drops.
    future = at + 1
    selected = rates[times >= future - 2 * DAY_MS]
    assert model.posterior(as_of=future) == fit(selected, interval_hours=8)
    assert model.training_summary(as_of=future)["training_settlements"] == 6
    snapshot = model.posterior()
    model.predict_cumulative_funding(3, as_of=future, draws=100)
    assert model.posterior() == snapshot  # prediction does not alter the observed history


def test_cadence_change_resets_and_uses_later_rows_spacing():
    model, times, rates = populated(days=90, n=5)
    timestamp = int(times[-1]) + 4 * HOUR_MS
    model.update(timestamp, 0.00001, 4)
    assert model.cadence_resets == 1
    with pytest.raises(FundingModelUnavailable, match="insufficient"):
        model.posterior()
    model.update(timestamp + 4 * HOUR_MS, 0.00002, 4)
    model.update(timestamp + 8 * HOUR_MS, -0.00003, 4)
    assert model.posterior() == fit([0.00001, 0.00002, -0.00003], interval_hours=4)
    assert model.training_summary()["training_first_time"] == timestamp


@pytest.mark.parametrize(
    "offset,rate,hours",
    [
        (0, 0.0, 8),
        (-1, 0.0, 8),
        (16 * HOUR_MS, 0.0, 8),
        (8 * HOUR_MS, np.nan, 8),
        (8 * HOUR_MS, np.inf, 8),
        (8 * HOUR_MS, 0.051, 8),
        (8 * HOUR_MS, 0.0, 0),
        (8 * HOUR_MS, 0.0, 25),
        (8 * HOUR_MS, 0.0, 8.0),
    ],
)
def test_bad_updates_do_not_change_state(offset, rate, hours):
    model, times, _ = populated()
    before = model.posterior()
    with pytest.raises(FundingHistoryError):
        model.update(int(times[-1]) + offset, rate, hours)
    assert model.posterior() == before
    assert model.cadence_resets == 0


def test_unavailable_stale_backdated_and_bad_configuration():
    empty = RollingFundingModel()
    with pytest.raises(FundingModelUnavailable, match="no observed"):
        empty.posterior()
    model, times, _ = populated()
    with pytest.raises(FundingHistoryError, match="precedes"):
        model.posterior(as_of=int(times[-1]) - 1)
    with pytest.raises(FundingModelUnavailable, match="stale"):
        model.posterior(as_of=int(times[-1]) + 8 * HOUR_MS + 5001)
    for kwargs in ({"rolling_days": 0}, {"rolling_days": True}, {"min_settlements": 2}):
        with pytest.raises(ValueError):
            RollingFundingModel(**kwargs)
    for horizon in (0, -1, 1.5, True):
        with pytest.raises(ValueError):
            model.predict_cumulative_funding(horizon)
    for kwargs in ({"draws": 1}, {"seed": -1}, {"seed": True}):
        with pytest.raises(ValueError):
            model.predict_cumulative_funding(3, **kwargs)


def test_recursive_samples_match_independent_manual_paths_exactly():
    model, times, rates = populated(days=90, n=50)
    posterior = model.posterior()
    coefficients, variance = posterior.sample(300, seed=17)
    current = np.full(300, rates[-1] * 10_000)
    total = np.zeros(300)
    rng = np.random.default_rng(18)
    for _ in range(4):
        current = (
            coefficients[:, 0]
            + coefficients[:, 1] * current
            + rng.standard_normal(300) * np.sqrt(variance)
        )
        total += current
    forecast = model.predict_cumulative_funding(4, draws=300, seed=17)
    np.testing.assert_array_equal(forecast.samples, total / 10_000)
    assert forecast == model.predict_cumulative_funding(4, draws=300, seed=17)
    assert forecast != model.predict_cumulative_funding(4, draws=300, seed=18)
    summary = forecast.summary()
    assert summary["as_of"] == int(times[-1])
    assert summary["horizon_settlements"] == 4 and summary["interval_hours"] == 8
    assert summary["positive_probability"] == np.mean(total > 0)
    assert forecast.probability_above(0.0001) == np.mean(total / 10_000 > 0.0001)
    assert summary["interval_95_fraction"] == np.quantile(total / 10_000, [0.025, 0.975]).tolist()
    with pytest.raises(ValueError):
        forecast.probability_above(np.inf)


def test_one_step_mc_matches_exact_student_and_multi_step_is_not_scaled_one_step():
    model, _, rates = populated(days=90, n=200)
    posterior = model.posterior()
    df, loc, scale = posterior.predict([rates[-1]])
    one = np.asarray(model.predict_cumulative_funding(1, draws=100_000, seed=18).samples)
    assert one.mean() == pytest.approx(loc[0], abs=3e-7, rel=0)
    assert one.var() == pytest.approx(float(scale[0] ** 2 * df / (df - 2)), rel=0.02)
    four = np.asarray(model.predict_cumulative_funding(4, draws=100_000, seed=18).samples)
    assert not np.array_equal(four, one * 4)


def test_predictive_innovation_and_persistence_propagate(monkeypatch):
    model, _, _ = populated(days=90, n=5)
    # Deterministic coefficients/variance distinguish recursive shocks from fresh-lag shortcuts.
    from perpcarry.models.funding_model import Posterior

    monkeypatch.setattr(
        Posterior,
        "sample",
        lambda self, size, seed: (np.tile([0.0, 0.8], (size, 1)), np.ones(size)),
    )
    one = np.asarray(model.predict_cumulative_funding(1, draws=80_000, seed=24).samples) * 10_000
    four = np.asarray(model.predict_cumulative_funding(4, draws=80_000, seed=24).samples) * 10_000
    # Each innovation contributes to the sum via 1+phi+...; the last innovation has weight 1.
    expected = sum(sum(0.8**j for j in range(length)) ** 2 for length in range(1, 5))
    assert one.var() == pytest.approx(1.0, rel=0.02)
    assert four.var() == pytest.approx(expected, rel=0.02)


def test_nonfinite_paths_fail_explicitly(monkeypatch):
    model, _, _ = populated()
    from perpcarry.models.funding_model import Posterior

    monkeypatch.setattr(
        Posterior, "sample", lambda self, size, seed: (np.full((size, 2), 1e308), np.ones(size))
    )
    with pytest.raises(FundingModelUnavailable, match="nonfinite"):
        model.predict_cumulative_funding(10, draws=10)


def test_cumulative_paths_do_not_clip_explosive_phi(monkeypatch):
    from perpcarry.models.funding_model import Posterior

    model, _, rates = populated()
    monkeypatch.setattr(
        Posterior,
        "sample",
        lambda self, size, seed: (np.tile([0.0, 1.2], (size, 1)), np.zeros(size)),
    )
    forecast = model.predict_cumulative_funding(5, draws=10)
    expected = rates[-1] * sum(1.2**j for j in range(1, 6))
    np.testing.assert_allclose(forecast.samples, expected, rtol=0, atol=2e-19)


def test_archive_jitter_and_integer_timestamps():
    model, times, _ = populated()
    next_time = int(times[-1]) + 8 * HOUR_MS + 5000
    model.update(next_time, 0.00001, 8)
    model.posterior(as_of=next_time + 8 * HOUR_MS + 5000)
    for timestamp in (True, float(next_time + 8 * HOUR_MS), -1):
        with pytest.raises(FundingHistoryError):
            model.update(timestamp, 0.00001, 8)
    with pytest.raises(FundingHistoryError, match="irregular"):
        model.update(next_time + 8 * HOUR_MS + 5001, 0.00001, 8)


def test_unavailable_stream_recovers_after_cadence_reset(funding_frame_factory):
    frame = funding_frame_factory(start="2025-09-01", end="2025-09-05")
    frame.loc[frame.index >= 6, "funding_interval_hours"] = 4
    first = int(frame.funding_time.iloc[5])
    frame.loc[frame.index >= 6, "funding_time"] = first + np.arange(1, 7) * 4 * HOUR_MS
    config = Config(min_settlements=3, horizons=(), draws=20)
    records = list(
        forecast_stream(
            frame, study_start=dt.date(2025, 9, 1), study_end=dt.date(2025, 9, 5), config=config
        )
    )
    assert [r["status"] for r in records[:4]] == ["unavailable"] * 3 + ["forecast"]
    assert [r["status"] for r in records[7:10]] == ["unavailable"] * 2 + ["forecast"]
    assert records[9]["training"]["training_settlements"] == 3
    assert records[9]["training"]["cadence_resets"] == 1
    assert records[9]["posterior"]["interval_hours"] == 4
    assert records[9]["frozen_one_step"]["df"] == records[9]["one_step"]["df"]


@pytest.mark.parametrize(
    "kwargs",
    [{"draws": 1}, {"seed": -1}, {"horizons": (1, 1)}, {"horizons": (0,)}, {"draws": True}],
)
def test_invalid_diagnostic_configuration(kwargs):
    with pytest.raises(ValueError):
        Config(**kwargs)


def test_historical_forecasts_unchanged_by_withheld_shuffled_or_poisoned_future(
    funding_frame_factory,
):
    frame = funding_frame_factory()
    start, end = dt.date(2025, 9, 1), dt.date(2025, 10, 3)
    config = Config(rolling_days=30, min_settlements=3, horizons=(3,), draws=100)

    def prefix(rows):
        return list(
            islice(forecast_stream(rows, study_start=start, study_end=end, config=config), 9)
        )

    reference = prefix(frame)
    boundary = frame.index[frame.funding_time == reference[-1]["funding_time"]][0]
    assert prefix(frame.iloc[: boundary + 1]) == reference
    shuffled = frame.copy()
    shuffled.iloc[boundary + 1 :] = (
        frame.iloc[boundary + 1 :].sample(frac=1, random_state=10).to_numpy()
    )
    assert prefix(shuffled) == reference
    poisoned = frame.copy()
    poisoned.loc[poisoned.index > boundary, "funding_rate"] = np.nan
    assert prefix(poisoned) == reference
    # Current value must also remain unknown at prediction time, not just later rows.
    poisoned.loc[boundary, "funding_rate"] = np.nan
    assert prefix(poisoned) == reference
    first = reference[0]
    assert first["training"]["last_observation_time"] < first["funding_time"]
    assert first["training"]["training_settlements"] == 90


def test_cumulative_scores_exclude_endpoints_and_changed_cadence(funding_frame_factory):
    frame = funding_frame_factory()
    start, end = dt.date(2025, 9, 1), dt.date(2025, 10, 3)
    config = Config(rolling_days=30, min_settlements=3, horizons=(3,), draws=100)
    records = list(forecast_stream(frame, study_start=start, study_end=end, config=config))
    study = frame[frame.funding_time >= records[0]["funding_time"]].copy()
    scored = score_cumulative(records, study, 3)
    assert scored["rows"] == 94 and scored["incomplete_endpoints"] == 2
    study.iloc[2, study.columns.get_loc("funding_interval_hours")] = 4
    changed = score_cumulative(records, study, 3)
    assert changed["rows"] == 91 and changed["cadence_excluded"] == 3
    # Hand-compute complete actual sums and interval comparisons.
    actual = study.funding_rate.to_numpy()
    expected = sum(
        r["cumulative"]["3"]["interval_95_fraction"][0]
        <= actual[i : i + 3].sum()
        <= r["cumulative"]["3"]["interval_95_fraction"][1]
        for i, r in enumerate(records[:-2])
    )
    assert scored["coverage_95"] == expected / 94
