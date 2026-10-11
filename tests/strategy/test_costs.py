"""M7-T1: admitted square-root execution costs, units, chronology and model integration."""

import datetime as dt
from dataclasses import replace

import pytest

from perpcarry.ingestion.funding_series import utc_ms
from perpcarry.integrity import sha256
from perpcarry.models import impact_model_io
from perpcarry.models.impact_model import ImpactModelError
from perpcarry.models.rolling_funding import HOUR_MS, RollingFundingModel
from perpcarry.strategy import costs, funding
from perpcarry.strategy.carry import CarryStrategy, FundingApproval, Policy

NOW = utc_ms(dt.date(2025, 9, 1))


@pytest.fixture
def kwargs():
    return dict(
        symbol="BTCUSDT",
        now_ms=NOW,
        valid_until_ms=NOW + 1000,
        notional_usdt=1000.0,
        adv_fraction=0.0004,
        horizon_settlements=3,
        schedule="static",
        depth="inside_validated_depth",
        size_regime="all_sizes",
        entry_half_spread_bps=1.2,
        close_half_spread_bps=1.7,
        entry_fee_bps=2.0,
        close_fee_bps=2.5,
        hedge_entry_bps=0.8,
        hedge_close_bps=0.9,
        financing_fraction=0.0002,
        allow_synthetic=True,
    )


@pytest.fixture
def path(impact_artifact_factory, tmp_path):
    path = tmp_path / "impact.json"
    impact_model_io.save(impact_artifact_factory(), path)
    return path


def test_sell_entry_buy_close_and_touch_relative_spread_added_once(path, kwargs):
    quote = costs.from_artifact(path, **kwargs)
    assert quote.entry_fraction == pytest.approx((0.4 + 1.2 + 2.0 + 0.8) / 10_000, rel=0, abs=1e-18)
    assert quote.close_now_fraction == pytest.approx(
        (0.6 + 1.7 + 2.5 + 0.9) / 10_000, rel=0, abs=1e-18
    )
    assert quote.terminal_close_fraction == quote.close_now_fraction
    assert quote.financing_fraction == 0.0002
    assert quote.notional_usdt == 1000.0 and quote.horizon_settlements == 3
    assert quote.artifact_sha256 == sha256(path)
    assert quote.evidence_end_exclusive_ms == NOW
    assert quote.kind == "synthetic"


@pytest.mark.parametrize(
    "changes,match",
    [
        ({"symbol": "SOLUSDT"}, "symbol"),
        ({"now_ms": NOW - 1}, "future"),
        ({"allow_synthetic": False}, "synthetic"),
        ({"adv_fraction": 0.000099}, "extrapolated"),
        ({"adv_fraction": 0.000901}, "extrapolated"),
        ({"schedule": "missing"}, "unavailable"),
        ({"size_regime": "missing"}, "unavailable"),
        ({"depth": "beyond_validated_depth"}, "validated order depth"),
    ],
)
def test_inadmissible_artifacts_have_no_substitute_quote(path, kwargs, changes, match):
    with pytest.raises(ImpactModelError, match=match):
        costs.from_artifact(path, **{**kwargs, **changes})


def test_both_sides_and_nonnegative_primary_law_required(impact_artifact_factory, tmp_path, kwargs):
    path = tmp_path / "impact.json"
    impact_model_io.save(impact_artifact_factory(sides=("sell",)), path)
    with pytest.raises(ImpactModelError, match="unavailable"):
        costs.from_artifact(path, **kwargs)
    artifact = impact_artifact_factory()
    for record in artifact["fits"]:
        if record["model"]["form"] == "square_root" and record["side"] == "buy":
            record["model"]["coefficient"] = -30.0
            record["usable_as_nonnegative_impact_law"] = False
    impact_model_io.save(artifact, path)
    with pytest.raises(ImpactModelError, match="unusable"):
        costs.from_artifact(path, **kwargs)


def test_stable_artifact_hash_is_required_during_load(path, kwargs, monkeypatch):
    original = impact_model_io.load

    def changed(path):
        artifact = original(path)
        path.write_text(path.read_text() + " ")
        return artifact

    monkeypatch.setattr(impact_model_io, "load", changed)
    with pytest.raises(ImpactModelError, match="changed while reading"):
        costs.from_artifact(path, **kwargs)


@pytest.mark.parametrize(
    "changes",
    [
        {"entry_half_spread_bps": -0.1},
        {"close_fee_bps": float("nan")},
        {"financing_fraction": float("inf")},
        {"adv_fraction": 0.0},
        {"notional_usdt": 0.0},
        {"horizon_settlements": 0},
        {"valid_until_ms": NOW},
    ],
)
def test_invalid_quote_inputs_reject(path, kwargs, changes):
    with pytest.raises(ValueError):
        costs.from_artifact(path, **{**kwargs, **changes})


def test_actual_m5_m6_interfaces_feed_synthetic_strategy_decision(path, kwargs):
    # Policy numbers exercise a branch; they are not a selected BTC research policy.
    model = RollingFundingModel()
    for i in range(40):
        model.update(NOW - (40 - i) * 8 * HOUR_MS + 137, 0.001, 8)
    forecast = funding.from_model("BTCUSDT", model, horizon=3, now_ms=NOW, draws=2000)
    quote = costs.from_artifact(path, **kwargs)
    approval = FundingApproval(
        "BTCUSDT", (1, 2, 3), 8, NOW, NOW + 1000, "c" * 64, True, forecast.model_sha256
    )
    strategy = CarryStrategy("BTCUSDT", Policy(3, 0.8, 0.5, allow_synthetic_costs=True))
    decision = strategy.decide(now_ms=NOW, forecast=forecast, costs=quote, approval=approval)
    assert decision.action == "enter" and decision.probability > 0.8
    assert decision.expected_incremental_fraction > 0
    assert (
        strategy.decide(now_ms=NOW, forecast=forecast, costs=quote, approval=None).action == "wait"
    )
    assert (
        strategy.decide(
            now_ms=NOW, forecast=forecast, costs=quote, approval=replace(approval, approved=False)
        ).action
        == "wait"
    )


def test_model_scope_changes_with_configuration_not_new_observations():
    from perpcarry.models.funding_model import Prior

    model = RollingFundingModel()
    original = funding.model_digest(model)
    model.update(NOW - HOUR_MS, 0.001, 8)
    assert funding.model_digest(model) == original
    for variant in (
        RollingFundingModel(rolling_days=30),
        RollingFundingModel(min_settlements=3),
        RollingFundingModel(prior=Prior(scale=8.0)),
    ):
        assert funding.model_digest(variant) != original
