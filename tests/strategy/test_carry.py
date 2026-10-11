"""M7-T1: synthetic coverage of every entry, continuation and exit decision branch."""

from dataclasses import replace

import numpy as np
import pytest

from perpcarry.models.rolling_funding import HOUR_MS, CumulativeFundingForecast
from perpcarry.strategy.carry import (
    CarryStrategy,
    CostEstimate,
    FundingApproval,
    FundingForecast,
    Policy,
    Position,
)

NOW = 2_000_000_000_000


@pytest.fixture
def inputs():
    # Synthetic metadata and distributions; no real validation approval is fabricated.
    forecast = FundingForecast(
        "BTCUSDT",
        CumulativeFundingForecast(
            (0.002,) * 9 + (-0.001,),
            3,
            8,
            NOW,
            NOW - HOUR_MS,
            NOW - 90 * 24 * HOUR_MS,
            270,
            4,
        ),
        "d" * 64,
    )
    costs = CostEstimate(
        "BTCUSDT",
        1000.0,
        3,
        NOW,
        NOW + 1000,
        NOW - 1000,
        "a" * 64,
        "synthetic",
        0.0002,
        0.0003,
        0.0003,
        0.0001,
    )
    approval = FundingApproval(
        "BTCUSDT", (1, 2, 3), 8, NOW - 1000, NOW + 1000, "b" * 64, True, "d" * 64
    )
    return dict(now_ms=NOW, forecast=forecast, costs=costs, approval=approval)


@pytest.fixture
def strategy():
    return CarryStrategy("BTCUSDT", Policy(3, 0.8, 0.5, allow_synthetic_costs=True))


def held(*, count=1, horizon=3):
    return Position("BTCUSDT", 1000.0, NOW - HOUR_MS, horizon, count, 8)


def with_remaining(inputs, remaining=2):
    values = inputs.copy()
    values["forecast"] = replace(
        inputs["forecast"],
        prediction=replace(inputs["forecast"].prediction, horizon_settlements=remaining),
    )
    values["costs"] = replace(inputs["costs"], horizon_settlements=remaining)
    return values


def test_enters_only_on_cost_adjusted_probability_and_positive_mean(strategy, inputs):
    decision = strategy.decide(**inputs)
    assert decision.action == "enter" and decision.reason == "positive_cost_adjusted_edge"
    assert decision.probability == 0.9
    assert decision.expected_incremental_fraction == pytest.approx(
        0.0017 - 0.0006, abs=1e-18, rel=0
    )
    assert strategy.decide(**inputs) == decision
    assert inputs["forecast"].prediction.samples == (0.002,) * 9 + (-0.001,)


def test_threshold_equality_waits_and_exactly_equal_funding_does_not_cover_cost(strategy, inputs):
    prediction = replace(inputs["forecast"].prediction, samples=(0.002,) * 8 + (-0.001,) * 2)
    decision = strategy.decide(
        **{**inputs, "forecast": replace(inputs["forecast"], prediction=prediction)}
    )
    assert decision.action == "wait" and decision.reason == "probability_below_threshold"
    assert decision.probability == 0.8
    hurdle = (
        inputs["costs"].entry_fraction
        + inputs["costs"].terminal_close_fraction
        + inputs["costs"].financing_fraction
    )
    prediction = replace(prediction, samples=(0.002,) * 8 + (hurdle,) * 2)
    decision = strategy.decide(
        **{**inputs, "forecast": replace(inputs["forecast"], prediction=prediction)}
    )
    assert decision.action == "wait" and decision.probability == 0.8


def test_high_positive_frequency_can_still_have_negative_expected_edge(strategy, inputs):
    prediction = replace(inputs["forecast"].prediction, samples=(0.001,) * 9 + (-0.1,))
    decision = strategy.decide(
        **{**inputs, "forecast": replace(inputs["forecast"], prediction=prediction)}
    )
    assert decision.probability == 0.9
    assert decision.action == "wait" and decision.reason == "nonpositive_expected_edge"


def test_zero_mean_edge_rejects_even_with_good_frequency(strategy, inputs):
    costs = replace(
        inputs["costs"],
        entry_fraction=0.0,
        close_now_fraction=0.0,
        terminal_close_fraction=0.0,
        financing_fraction=0.0,
    )
    prediction = replace(inputs["forecast"].prediction, samples=(0.0, 0.0))
    decision = strategy.decide(
        **{**inputs, "costs": costs, "forecast": replace(inputs["forecast"], prediction=prediction)}
    )
    assert decision.action == "wait" and decision.expected_incremental_fraction == 0


def test_continuation_uses_remaining_horizon_and_ignores_sunk_entry_cost(strategy, inputs):
    values = with_remaining(inputs)
    decision = strategy.decide(**values, position=held())
    assert decision.action == "hold" and decision.expected_incremental_fraction == pytest.approx(
        0.0016, abs=1e-18, rel=0
    )
    higher_entry = replace(values["costs"], entry_fraction=1.0)
    assert strategy.decide(**{**values, "costs": higher_entry}, position=held()) == decision
    # A new full-length forecast cannot keep extending the original horizon.
    extended = strategy.decide(**inputs, position=held())
    assert extended.action == "exit" and extended.reason == "invalid_funding_forecast"


def test_continuation_compares_deferred_close_to_immediate_close(strategy, inputs):
    values = with_remaining(inputs)
    prediction = replace(values["forecast"].prediction, samples=(-0.0001,) * 10)
    values["forecast"] = replace(values["forecast"], prediction=prediction)
    values["costs"] = replace(
        values["costs"],
        close_now_fraction=0.001,
        terminal_close_fraction=0.0001,
        financing_fraction=0.0,
    )
    assert strategy.decide(**values, position=held()).action == "hold"
    values["costs"] = replace(
        values["costs"], close_now_fraction=0.0001, terminal_close_fraction=0.001
    )
    assert strategy.decide(**values, position=held()).reason == "nonpositive_expected_edge"


def test_continuation_probability_boundary_exits(strategy, inputs):
    values = with_remaining(inputs)
    prediction = replace(values["forecast"].prediction, samples=(0.003,) * 5 + (-0.001,) * 5)
    values["forecast"] = replace(values["forecast"], prediction=prediction)
    decision = strategy.decide(**values, position=held())
    assert decision.action == "exit" and decision.reason == "probability_below_threshold"
    assert decision.probability == 0.5 and decision.expected_incremental_fraction > 0


def test_horizon_complete_exit_intent_needs_no_predictor_or_cost(strategy):
    decision = strategy.decide(
        now_ms=NOW, forecast=None, costs=None, approval=None, position=held(count=3)
    )
    assert decision.action == "exit" and decision.reason == "horizon_complete"


@pytest.mark.parametrize("position", [False, True])
@pytest.mark.parametrize(
    "missing,reason",
    [
        ("forecast", "funding_unavailable"),
        ("costs", "costs_unavailable"),
        ("approval", "funding_not_admitted"),
    ],
)
def test_missing_inputs_wait_or_exit_intent(strategy, inputs, position, missing, reason):
    values = with_remaining(inputs) if position else inputs.copy()
    values[missing] = None
    decision = strategy.decide(**values, position=held() if position else None)
    assert decision.action == ("exit" if position else "wait") and decision.reason == reason


@pytest.mark.parametrize(
    "changes",
    [
        {"as_of": NOW - 1},
        {"as_of": NOW + 1},
        {"last_observation_time": NOW + 1},
        {"last_observation_time": NOW - 9 * HOUR_MS},
        {"training_first_time": NOW},
        {"horizon_settlements": 21},
        {"horizon_settlements": 3.0},
        {"interval_hours": 0},
        {"interval_hours": 25},
        {"training_settlements": 2},
        {"training_first_time": -1},
        {"samples": ()},
        {"samples": (0.001,)},
        {"samples": (np.nan, 0.001)},
        {"samples": (np.inf, 0.001)},
        {"samples": ("bad", 0.001)},
        {"samples": ((0.001, 0.002), (0.001, 0.002))},
    ],
)
def test_invalid_forecasts_never_enter(strategy, inputs, changes):
    prediction = replace(inputs["forecast"].prediction, **changes)
    decision = strategy.decide(
        **{**inputs, "forecast": replace(inputs["forecast"], prediction=prediction)}
    )
    assert decision.action == "wait" and decision.reason == "invalid_funding_forecast"


def test_wrong_forecast_symbol_and_changed_held_cadence(strategy, inputs):
    forecast = replace(inputs["forecast"], symbol="SOLUSDT")
    assert strategy.decide(**{**inputs, "forecast": forecast}).reason == "invalid_funding_forecast"
    values = with_remaining(inputs)
    values["forecast"] = replace(
        values["forecast"], prediction=replace(values["forecast"].prediction, interval_hours=4)
    )
    decision = strategy.decide(**values, position=held())
    assert decision.action == "exit" and decision.reason == "cadence_changed"


@pytest.mark.parametrize(
    "changes",
    [
        {"approved": False},
        {"model_sha256": "c" * 64},
        {"symbol": "SOLUSDT"},
        {"horizons": (21,)},
        {"interval_hours": 4},
        {"validation_end_exclusive_ms": NOW + 1},
        {"valid_until_ms": NOW},
    ],
)
def test_approval_cannot_use_future_wrong_scope_or_expired_evidence(strategy, inputs, changes):
    approval = replace(inputs["approval"], **changes)
    assert strategy.decide(**{**inputs, "approval": approval}).reason == "funding_not_admitted"


@pytest.mark.parametrize(
    "changes",
    [
        {"symbol": "SOLUSDT"},
        {"horizon_settlements": 21},
        {"quoted_at_ms": NOW + 1},
        {"evidence_end_exclusive_ms": NOW + 1},
    ],
)
def test_unusable_cost_evidence_never_enters(strategy, inputs, changes):
    costs = replace(inputs["costs"], **changes)
    assert strategy.decide(**{**inputs, "costs": costs}).reason == "costs_not_admitted"


def test_quote_expiry_and_notional_mismatch(strategy, inputs):
    costs = replace(inputs["costs"], quoted_at_ms=NOW - 1000, valid_until_ms=NOW)
    assert strategy.decide(**{**inputs, "costs": costs}).reason == "costs_not_admitted"
    values = with_remaining(inputs)
    values["costs"] = replace(values["costs"], notional_usdt=2000.0)
    assert strategy.decide(**values, position=held()).reason == "costs_not_admitted"


def test_synthetic_impact_is_disabled_by_default(inputs):
    strategy = CarryStrategy("BTCUSDT", Policy(3, 0.8, 0.5))
    assert strategy.decide(**inputs).reason == "costs_not_admitted"


def test_nonfinite_mean_and_invalid_position_context(strategy, inputs):
    prediction = replace(inputs["forecast"].prediction, samples=(1e308,) * 10)
    assert (
        strategy.decide(
            **{**inputs, "forecast": replace(inputs["forecast"], prediction=prediction)}
        ).reason
        == "nonfinite_expected_edge"
    )
    for changes in ({"symbol": "SOLUSDT"}, {"opened_at_ms": NOW + 1}):
        with pytest.raises(ValueError, match="position"):
            strategy.decide(**inputs, position=replace(held(), **changes))
    with pytest.raises(ValueError):
        strategy.decide(**{**inputs, "now_ms": True})


@pytest.mark.parametrize(
    "kwargs",
    [
        {"horizon_settlements": 0},
        {"horizon_settlements": True},
        {"entry_probability": 1},
        {"entry_probability": 0.5},
        {"continuation_probability": -0.1},
        {"entry_probability": float("nan")},
        {"allow_synthetic_costs": 1},
    ],
)
def test_policy_requires_explicit_valid_parameters(kwargs):
    fields = dict(horizon_settlements=3, entry_probability=0.8, continuation_probability=0.5)
    with pytest.raises(ValueError):
        Policy(**{**fields, **kwargs})


@pytest.mark.parametrize(
    "changes",
    [
        {"artifact_sha256": "invalid"},
        {"kind": "assumed_flat"},
        {"entry_fraction": -0.1},
        {"notional_usdt": 0},
        {"financing_fraction": float("inf")},
    ],
)
def test_invalid_cost_records_reject(inputs, changes):
    with pytest.raises(ValueError):
        replace(inputs["costs"], **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"evidence_sha256": "invalid"},
        {"model_sha256": "invalid"},
        {"approved": 1},
        {"horizons": (3, 3)},
        {"horizons": ()},
        {"interval_hours": 25},
    ],
)
def test_invalid_approval_records_reject(inputs, changes):
    with pytest.raises(ValueError):
        replace(inputs["approval"], **changes)


def test_invalid_scope_records_reject(inputs):
    with pytest.raises(ValueError):
        CarryStrategy("", Policy(3, 0.8, 0.5))
    with pytest.raises(ValueError):
        replace(held(), interval_hours=25)
    for changes in ({"symbol": ""}, {"prediction": None}, {"model_sha256": "invalid"}):
        with pytest.raises(ValueError):
            replace(inputs["forecast"], **changes)
