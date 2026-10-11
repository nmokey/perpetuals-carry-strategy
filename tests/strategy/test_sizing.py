"""M7-T2: hand-computed marginal impact, probability and executable-size cases."""

import datetime as dt
from dataclasses import replace
from decimal import Decimal

import pytest

from perpcarry.ingestion.funding_series import utc_ms
from perpcarry.models import impact_model_io
from perpcarry.models.impact_model import ImpactModelError
from perpcarry.models.rolling_funding import (
    DAY_MS,
    HOUR_MS,
    CumulativeFundingForecast,
    RollingFundingModel,
)
from perpcarry.strategy import costs, funding, sizing
from perpcarry.strategy.carry import CarryStrategy, FundingApproval, FundingForecast, Policy

NOW = utc_ms(dt.date(2025, 9, 1)) + 137


@pytest.fixture
def inputs():
    market = sizing.SizingInputs(
        "BTCUSDT",
        NOW,
        NOW + 1000,
        100.0,
        1000.0,
        NOW // DAY_MS * DAY_MS - 30 * DAY_MS,
        NOW // DAY_MS * DAY_MS,
        "a" * 64,
        Decimal(".1"),
        Decimal(".1"),
        0.0,
        10000.0,
        0.01,
        100.0,
        NOW - 1000,
        NOW + 1000,
        "b" * 64,
    )
    curve = costs.ImpactCurve(
        "BTCUSDT", NOW, NOW - 1000, "c" * 64, "synthetic", 400.0, 600.0, 0.0001, 0.01
    )
    charges = sizing.ExecutionCharges(1.0, 2.0, 3.0, 4.0, 0.0, 0.0, 0.0002)
    prediction = CumulativeFundingForecast(
        (0.0072,) * 10, 3, 8, NOW, NOW - HOUR_MS, NOW - 90 * DAY_MS, 270, 4
    )
    forecast = FundingForecast("BTCUSDT", prediction, "d" * 64)
    approval = FundingApproval("BTCUSDT", (3,), 8, NOW - 1000, NOW + 1000, "e" * 64, True, "d" * 64)
    return dict(
        now_ms=NOW,
        market=market,
        curve=curve,
        charges=charges,
        forecast=forecast,
        approval=approval,
    )


@pytest.fixture
def strategy():
    return CarryStrategy("BTCUSDT", Policy(3, 0.8, 0.5, allow_synthetic_costs=True))


def run(strategy, inputs, *, market=None, curve=None, samples=None, charges=None):
    args = dict(inputs)
    if market:
        args["market"] = replace(args["market"], **market)
    if curve:
        args["curve"] = replace(args["curve"], **curve)
    if charges:
        args["charges"] = replace(args["charges"], **charges)
    if samples is not None:
        args["forecast"] = replace(
            args["forecast"], prediction=replace(args["forecast"].prediction, samples=samples)
        )
    return sizing.size_position(strategy, **args)


def test_marginal_optimum_differs_from_break_even_capacity(strategy, inputs):
    result = run(strategy, inputs)
    # e=.006, K=.1 -> x*=(.006/.15)^2=.0016; x0=(.006/.1)^2=.0036.
    assert result.quantity_base == Decimal("1.6")
    assert result.adv_fraction == 0.0016 and result.notional_usdt == 160.0
    assert result.expected_net_usdt == pytest.approx(0.32, rel=0, abs=1e-15)
    assert result.marginal_net_fraction == pytest.approx(0, rel=0, abs=1e-17)
    assert result.break_even_adv_fraction == pytest.approx(0.0036, rel=0, abs=1e-17)
    assert result.break_even_status == "within_support"
    assert result.break_even_notional_usdt == pytest.approx(360.0, rel=0, abs=1e-12)
    assert result.feasible_max_notional_usdt == result.feasible_max_adv_fraction * 100_000
    assert result.feasible_max_adv_fraction > result.adv_fraction
    assert result.decision.action == "enter"
    assert run(strategy, inputs) == result


def test_discrete_optimum_can_round_up_when_more_profitable(strategy, inputs):
    # Continuous optimum quantity = 1.69; step=.3 -> compare 1.5 and 1.8, choose 1.8.
    result = run(
        strategy,
        inputs,
        samples=(0.0012 + 0.15 * (0.00169**0.5),) * 10,
        market={"quantity_step": Decimal(".3")},
    )
    assert result.quantity_base == Decimal("1.8")
    for quantity in (
        Decimal(".3"),
        Decimal(".6"),
        Decimal(".9"),
        Decimal("1.2"),
        Decimal("1.5"),
        Decimal("2.1"),
        Decimal("2.4"),
    ):
        x = float(quantity / Decimal(1000))
        mean = 0.0012 + 0.15 * (0.00169**0.5)
        profit = float(quantity) * 100 * (mean - 0.0012 - 0.1 * x**0.5)
        assert result.expected_net_usdt > profit


@pytest.mark.parametrize(
    "bound,limit",
    [
        ({"max_adv_fraction": 0.00105}, "max_adv"),
        ({"max_notional_usdt": 105.0}, "max_notional"),
        ({"validated_quantity_base": 1.05}, "validated_depth"),
    ],
)
def test_hard_caps_round_down_and_report_binding_limit(strategy, inputs, bound, limit):
    result = run(strategy, inputs, market=bound)
    assert result.quantity_base == Decimal("1.0")
    assert result.adv_fraction == 0.001
    assert limit in result.binding_limits
    assert result.marginal_net_fraction > 0


def test_model_support_caps_without_claiming_true_capacity(strategy, inputs):
    result = run(strategy, inputs, curve={"size_max": 0.00105})
    assert result.quantity_base == Decimal("1.0")
    assert "model_support" in result.binding_limits
    assert result.break_even_adv_fraction is None and result.break_even_status == "above_support"
    assert result.break_even_notional_usdt is None


def test_probability_gate_caps_size_even_when_mean_optimum_is_larger(strategy, inputs):
    # 8/10 paths exceed costs at x>=.000324: equality with .8 must reject.
    result = run(strategy, inputs, samples=(0.02,) * 8 + (0.003,) * 2)
    assert result.quantity_base == Decimal(".3")
    assert result.feasible_max_adv_fraction == 0.0003
    assert result.decision.probability == 1.0
    assert "entry_gate" in result.binding_limits
    assert result.marginal_net_fraction > 0


def test_minimum_feasible_size_can_be_optimum_but_must_remain_profitable(strategy, inputs):
    result = run(strategy, inputs, market={"min_quantity": Decimal("2.1")})
    assert result.quantity_base == Decimal("2.1")
    assert result.expected_net_usdt > 0 and result.marginal_net_fraction < 0
    result = run(strategy, inputs, market={"min_notional_usdt": 370.0})
    assert result.quantity_base == 0 and result.decision.action == "wait"


@pytest.mark.parametrize(
    "changes",
    [
        {"max_notional_usdt": 5.0},
        {"max_adv_fraction": 0.00009},
        {"validated_quantity_base": 0.05},
        {"quantity_step": Decimal("100")},
        {"min_quantity": Decimal("200")},
        {"min_notional_usdt": 20000.0},
    ],
)
def test_empty_executable_range_waits(strategy, inputs, changes):
    result = run(strategy, inputs, market=changes)
    assert result.quantity_base == 0 and result.decision.reason == "no_executable_size"


def test_negative_mean_and_uncovered_fixed_costs_return_no_position(strategy, inputs):
    for samples in ((0.001,) * 10, (0.02,) * 9 + (-1.0,)):
        result = run(strategy, inputs, samples=samples)
        assert result.quantity_base == 0
        assert result.decision.reason == "nonpositive_expected_edge"


def test_zero_impact_uses_finite_cap_not_infinite_capacity(strategy, inputs):
    result = run(
        strategy,
        inputs,
        curve={"sell_coefficient_bps": 0.0, "buy_coefficient_bps": 0.0},
        market={"validated_quantity_base": 2.05},
    )
    assert result.quantity_base == Decimal("2.0")
    assert result.break_even_adv_fraction is None and result.break_even_status == "no_finite_root"
    assert result.expected_net_usdt == pytest.approx(1.2, rel=0, abs=1e-15)


@pytest.mark.parametrize(
    "changes",
    [
        {"symbol": "SOLUSDT"},
        {"observed_at_ms": NOW + 1},
        {"valid_until_ms": NOW},
        {
            "adv_end_exclusive_ms": NOW // DAY_MS * DAY_MS + DAY_MS,
            "adv_start_ms": NOW // DAY_MS * DAY_MS - 29 * DAY_MS,
        },
        {
            "adv_end_exclusive_ms": NOW // DAY_MS * DAY_MS - DAY_MS,
            "adv_start_ms": NOW // DAY_MS * DAY_MS - 31 * DAY_MS,
        },
        {"metadata_valid_from_ms": NOW + 1},
        {"metadata_valid_until_ms": NOW},
    ],
)
def test_future_stale_wrong_scope_inputs_cannot_size(strategy, inputs, changes):
    # A quote may originate earlier than now, but must still be within its explicit validity.
    if changes.get("valid_until_ms") == NOW:
        changes = {**changes, "observed_at_ms": NOW - 1}
    result = run(strategy, inputs, market=changes)
    assert result.quantity_base == 0 and result.decision.reason == "sizing_inputs_not_admitted"


@pytest.mark.parametrize(
    "changes",
    [
        {"symbol": "SOLUSDT"},
        {"admitted_at_ms": NOW + 1},
        {"evidence_end_exclusive_ms": NOW + 1},
    ],
)
def test_curve_scope_and_chronology_cannot_size(strategy, inputs, changes):
    assert run(strategy, inputs, curve=changes).decision.reason == "sizing_inputs_not_admitted"


def test_t1_approval_and_synthetic_default_cannot_be_bypassed(strategy, inputs):
    for approval in (
        None,
        replace(inputs["approval"], approved=False),
        replace(inputs["approval"], model_sha256="f" * 64),
    ):
        result = sizing.size_position(strategy, **{**inputs, "approval": approval})
        assert result.quantity_base == 0 and result.decision.reason == "funding_not_admitted"
    result = sizing.size_position(CarryStrategy("BTCUSDT", Policy(3, 0.8, 0.5)), **inputs)
    assert result.quantity_base == 0 and result.decision.reason == "costs_not_admitted"


@pytest.mark.parametrize(
    "changes",
    [
        {"price_usdt": 0.0},
        {"adv_base": float("nan")},
        {"max_adv_fraction": -1.0},
        {"quantity_step": 0.1},
        {"quantity_step": Decimal("0")},
        {"quantity_step": Decimal("NaN")},
        {"min_quantity": Decimal("-1")},
        {"adv_sha256": "bad"},
        {"metadata_sha256": "bad"},
        {"adv_start_ms": 0},
        {"adv_end_exclusive_ms": NOW},
        {"metadata_valid_until_ms": NOW - 1000},
        {"validated_quantity_base": 0.0},
    ],
)
def test_invalid_sizing_records_reject(inputs, changes):
    with pytest.raises(ValueError):
        replace(inputs["market"], **changes)


def test_invalid_cost_curves_and_charges_reject(inputs):
    for changes in (
        {"sell_coefficient_bps": -1},
        {"buy_coefficient_bps": float("inf")},
        {"size_min": 0},
        {"size_max": 0.00001},
    ):
        with pytest.raises(ValueError):
            replace(inputs["curve"], **changes)
    with pytest.raises(ValueError):
        replace(inputs["charges"], hedge_entry_bps=-1)
    with pytest.raises(ValueError):
        replace(inputs["charges"], financing_fraction=float("inf"))


def test_actual_m5_m6_t1_interfaces_feed_synthetic_sizing(
    strategy, inputs, impact_artifact_factory, tmp_path
):
    path = tmp_path / "impact.json"
    impact_model_io.save(impact_artifact_factory(), path)
    curve = costs.load_curve(
        path,
        symbol="BTCUSDT",
        now_ms=NOW,
        schedule="static",
        depth="inside_validated_depth",
        size_regime="all_sizes",
        allow_synthetic=True,
    )
    model = RollingFundingModel()
    for i in range(40):
        model.update(NOW - (40 - i) * 8 * HOUR_MS + 137, 0.0001, 8)
    forecast = funding.from_model("BTCUSDT", model, horizon=3, now_ms=NOW, draws=2000)
    approval = replace(inputs["approval"], model_sha256=forecast.model_sha256)
    result = sizing.size_position(
        strategy,
        **{
            **inputs,
            "curve": curve,
            "forecast": forecast,
            "approval": approval,
            "charges": sizing.ExecutionCharges(0, 0, 0, 0, 0, 0, 0),
        },
    )
    assert result.quantity_base > 0
    assert curve.size_min <= result.adv_fraction <= curve.size_max
    assert result.cost_estimate.entry_fraction == pytest.approx(
        20 * result.adv_fraction**0.5 / 10_000, rel=0, abs=1e-18
    )
    assert result.decision == strategy.decide(
        now_ms=NOW, forecast=forecast, costs=result.cost_estimate, approval=approval
    )
    assert result.quantity_base % inputs["market"].quantity_step == 0


def test_curve_uses_intersection_and_rejects_disjoint_supported_sizes(
    impact_artifact_factory, tmp_path
):
    artifact = impact_artifact_factory()
    path = tmp_path / "impact.json"
    for record in artifact["fits"]:
        if record["side"] == "buy":
            record["training_size_min"] = 0.0002
            record["training_size_max"] = 0.0008
    impact_model_io.save(artifact, path)
    kwargs = dict(
        symbol="BTCUSDT",
        now_ms=NOW,
        schedule="static",
        depth="inside_validated_depth",
        size_regime="all_sizes",
        allow_synthetic=True,
    )
    curve = costs.load_curve(path, **kwargs)
    assert curve.size_min == 0.0002 and curve.size_max == 0.0008
    for record in artifact["fits"]:
        if record["side"] == "buy":
            record["training_size_min"] = 0.001
            record["training_size_max"] = 0.002
    impact_model_io.save(artifact, path)
    with pytest.raises(ImpactModelError, match="no common"):
        costs.load_curve(path, **kwargs)


@pytest.mark.parametrize("mean", [0.0021, 0.003, 0.0049, 0.0072, 0.015, 0.1])
def test_matches_independent_exhaustive_executable_grid(strategy, inputs, mean):
    result = run(strategy, inputs, samples=(mean,) * 10)
    # Independent enumeration: zero and every .1-base lot inside [.1, 10].
    valid = [(0.0, Decimal(0))]
    for count in range(1, 101):
        q = Decimal(count) / Decimal(10)
        cost = 0.0012 + 0.1 * (float(q) / 1000) ** 0.5
        if mean > cost:
            valid.append((float(q) * 100 * (mean - cost), q))
    expected = max(valid, key=lambda pair: (pair[0], -pair[1]))
    assert result.quantity_base == expected[1]
    assert result.expected_net_usdt == pytest.approx(expected[0], rel=0, abs=1e-13)


def test_minimum_notional_and_support_floor_round_up(strategy, inputs):
    result = run(strategy, inputs, market={"min_notional_usdt": 211.0})
    assert result.quantity_base == Decimal("2.2") and result.notional_usdt >= 211
    result = run(strategy, inputs, curve={"size_min": 0.00215})
    assert result.quantity_base == Decimal("2.2")


def test_exact_profit_tie_prefers_smaller_lot(strategy, inputs, monkeypatch):
    original = strategy.decide

    def equal_profit(**kwargs):
        decision = original(**kwargs)
        return replace(
            decision,
            action="enter",
            expected_incremental_fraction=1 / kwargs["costs"].notional_usdt,
        )

    monkeypatch.setattr(strategy, "decide", equal_profit)
    result = run(strategy, inputs, samples=(0.0012 + 0.15 * 0.00015**0.5,) * 10)
    assert result.expected_net_usdt == 1
    assert result.quantity_base == Decimal(".1")


@pytest.mark.parametrize(
    "changes,match",
    [
        ({"now_ms": NOW - 138}, "future"),
        ({"symbol": "SOLUSDT"}, "symbol"),
        ({"allow_synthetic": False}, "synthetic"),
        ({"depth": "beyond_validated_depth"}, "validated order depth"),
    ],
)
def test_curve_loader_rejects_unadmitted_evidence_before_sizing(
    impact_artifact_factory, tmp_path, changes, match
):
    path = tmp_path / "impact.json"
    impact_model_io.save(impact_artifact_factory(), path)
    args = dict(
        symbol="BTCUSDT",
        now_ms=NOW,
        schedule="static",
        depth="inside_validated_depth",
        size_regime="all_sizes",
        allow_synthetic=True,
    )
    with pytest.raises(ImpactModelError, match=match):
        costs.load_curve(path, **{**args, **changes})
