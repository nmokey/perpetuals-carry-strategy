"""M7-T1: deterministic funding/cost decisions; actions are intents, not filled orders."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

import numpy as np

from perpcarry.models.rolling_funding import HOUR_MS, JITTER_MS, CumulativeFundingForecast


def integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")


def number(value, name, minimum=0.0):
    if type(value) not in (int, float) or not math.isfinite(value) or value < minimum:
        raise ValueError(f"{name} must be finite and >= {minimum}")


@dataclass(frozen=True)
class Policy:
    horizon_settlements: int
    entry_probability: float
    continuation_probability: float
    allow_synthetic_costs: bool = False

    def __post_init__(self):
        integer(self.horizon_settlements, "horizon_settlements", 1)
        number(self.entry_probability, "entry_probability")
        number(self.continuation_probability, "continuation_probability")
        if not 0 <= self.continuation_probability < self.entry_probability < 1:
            raise ValueError("require 0 <= continuation < entry < 1")
        if type(self.allow_synthetic_costs) is not bool:
            raise ValueError("explicit boolean synthetic-cost policy required")


@dataclass(frozen=True)
class Position:
    symbol: str
    notional_usdt: float
    opened_at_ms: int
    planned_settlements: int
    settlements_held: int
    interval_hours: int

    def __post_init__(self):
        number(self.notional_usdt, "notional_usdt")
        if not isinstance(self.symbol, str) or not self.symbol or self.notional_usdt == 0:
            raise ValueError("symbol and positive notional required")
        integer(self.opened_at_ms, "opened_at_ms")
        integer(self.planned_settlements, "planned_settlements", 1)
        integer(self.settlements_held, "settlements_held")
        integer(self.interval_hours, "interval_hours", 1)
        if self.interval_hours > 24:
            raise ValueError("invalid funding interval")


@dataclass(frozen=True)
class FundingApproval:
    symbol: str
    horizons: tuple[int, ...]
    interval_hours: int
    validation_end_exclusive_ms: int
    valid_until_ms: int
    evidence_sha256: str
    approved: bool
    model_sha256: str

    def __post_init__(self):
        if (
            not isinstance(self.symbol, str)
            or not self.symbol
            or not isinstance(self.horizons, tuple)
            or not self.horizons
        ):
            raise ValueError("symbol and immutable approved-horizon scope required")
        for horizon in self.horizons:
            integer(horizon, "approved horizon", 1)
        if len(set(self.horizons)) != len(self.horizons):
            raise ValueError("duplicate approved horizons")
        integer(self.interval_hours, "interval_hours", 1)
        integer(self.validation_end_exclusive_ms, "validation_end_exclusive_ms")
        integer(self.valid_until_ms, "valid_until_ms", self.validation_end_exclusive_ms + 1)
        if self.interval_hours > 24 or type(self.approved) is not bool:
            raise ValueError("invalid cadence or approval verdict")
        if not isinstance(self.evidence_sha256, str) or not re.fullmatch(
            r"[0-9a-f]{64}", self.evidence_sha256
        ):
            raise ValueError("funding approval requires evidence digest")
        if not isinstance(self.model_sha256, str) or not re.fullmatch(
            r"[0-9a-f]{64}", self.model_sha256
        ):
            raise ValueError("funding approval requires model/configuration digest")


@dataclass(frozen=True)
class FundingForecast:
    """Bind the symbol-less M6 distribution to its caller's per-symbol model instance."""

    symbol: str
    prediction: CumulativeFundingForecast
    model_sha256: str

    def __post_init__(self):
        if not isinstance(self.symbol, str) or not self.symbol:
            raise ValueError("funding forecast symbol required")
        if not isinstance(self.prediction, CumulativeFundingForecast):
            raise ValueError("M6 cumulative funding distribution required")
        if not isinstance(self.model_sha256, str) or not re.fullmatch(
            r"[0-9a-f]{64}", self.model_sha256
        ):
            raise ValueError("funding forecast requires model/configuration digest")


@dataclass(frozen=True)
class CostEstimate:
    symbol: str
    notional_usdt: float
    horizon_settlements: int
    quoted_at_ms: int
    valid_until_ms: int
    evidence_end_exclusive_ms: int
    artifact_sha256: str
    kind: str
    entry_fraction: float
    close_now_fraction: float
    terminal_close_fraction: float
    financing_fraction: float

    def __post_init__(self):
        number(self.notional_usdt, "notional_usdt")
        if not isinstance(self.symbol, str) or not self.symbol or not self.notional_usdt:
            raise ValueError("symbol and positive notional required")
        integer(self.horizon_settlements, "horizon_settlements", 1)
        integer(self.quoted_at_ms, "quoted_at_ms")
        integer(self.valid_until_ms, "valid_until_ms", self.quoted_at_ms + 1)
        integer(self.evidence_end_exclusive_ms, "evidence_end_exclusive_ms")
        if self.kind not in ("verified_calibration", "synthetic"):
            raise ValueError("cost requires calibrated or explicitly synthetic provenance")
        if not isinstance(self.artifact_sha256, str) or not re.fullmatch(
            r"[0-9a-f]{64}", self.artifact_sha256
        ):
            raise ValueError("cost requires artifact digest")
        for name in (
            "entry_fraction",
            "close_now_fraction",
            "terminal_close_fraction",
            "financing_fraction",
        ):
            number(getattr(self, name), name)


@dataclass(frozen=True)
class Decision:
    action: str
    reason: str
    probability: float | None = None
    expected_incremental_fraction: float | None = None


class CarryStrategy:
    def __init__(self, symbol: str, policy: Policy):
        if not isinstance(symbol, str) or not symbol:
            raise ValueError("symbol required")
        self.symbol, self.policy = symbol, policy

    def decide(
        self,
        *,
        now_ms: int,
        forecast: FundingForecast | None,
        costs: CostEstimate | None,
        approval: FundingApproval | None,
        position: Position | None = None,
    ) -> Decision:
        integer(now_ms, "now_ms")
        blocked = "wait" if position is None else "exit"
        if position is not None:
            if position.symbol != self.symbol or position.opened_at_ms > now_ms:
                raise ValueError("position symbol/time disagrees with decision")
            remaining = position.planned_settlements - position.settlements_held
            if remaining <= 0:
                return Decision("exit", "horizon_complete")
        else:
            remaining = self.policy.horizon_settlements
        if forecast is None:
            return Decision(blocked, "funding_unavailable")
        if forecast.symbol != self.symbol:
            return Decision(blocked, "invalid_funding_forecast")
        model_digest = forecast.model_sha256
        forecast = forecast.prediction
        if position is not None and forecast.interval_hours != position.interval_hours:
            return Decision("exit", "cadence_changed")
        try:
            samples = np.asarray(forecast.samples, dtype=float)
        except (TypeError, ValueError):
            return Decision(blocked, "invalid_funding_forecast")
        metadata = (
            forecast.as_of,
            forecast.last_observation_time,
            forecast.training_first_time,
            forecast.horizon_settlements,
            forecast.interval_hours,
            forecast.training_settlements,
        )
        if (
            samples.ndim != 1
            or len(samples) < 2
            or not np.isfinite(samples).all()
            or any(type(value) is not int or value < 0 for value in metadata)
            or forecast.as_of != now_ms
            or forecast.last_observation_time > now_ms
            or now_ms - forecast.last_observation_time
            > forecast.interval_hours * HOUR_MS + JITTER_MS
            or forecast.training_first_time > forecast.last_observation_time
            or forecast.horizon_settlements != remaining
            or not 1 <= forecast.interval_hours <= 24
            or forecast.training_settlements < 3
        ):
            return Decision(blocked, "invalid_funding_forecast")
        if (
            approval is None
            or not approval.approved
            or approval.symbol != self.symbol
            or approval.model_sha256 != model_digest
            or remaining not in approval.horizons
            or approval.interval_hours != forecast.interval_hours
            or approval.validation_end_exclusive_ms > now_ms
            or now_ms >= approval.valid_until_ms
        ):
            return Decision(blocked, "funding_not_admitted")
        if costs is None:
            return Decision(blocked, "costs_unavailable")
        if (
            costs.symbol != self.symbol
            or costs.horizon_settlements != remaining
            or costs.quoted_at_ms > now_ms
            or now_ms >= costs.valid_until_ms
            or costs.evidence_end_exclusive_ms > now_ms
            or (costs.kind == "synthetic" and not self.policy.allow_synthetic_costs)
            or (position is not None and costs.notional_usdt != position.notional_usdt)
        ):
            return Decision(blocked, "costs_not_admitted")
        if position is None:
            hurdle = costs.entry_fraction + costs.terminal_close_fraction + costs.financing_fraction
            probability_threshold = self.policy.entry_probability
        else:
            hurdle = (
                costs.terminal_close_fraction - costs.close_now_fraction + costs.financing_fraction
            )
            probability_threshold = self.policy.continuation_probability
        probability = float(np.mean(samples > hurdle))
        with np.errstate(over="ignore", invalid="ignore"):
            edge = float(samples.mean() - hurdle)
        if not math.isfinite(edge):
            return Decision(blocked, "nonfinite_expected_edge")
        if edge <= 0:
            return Decision(blocked, "nonpositive_expected_edge", probability, edge)
        if probability <= probability_threshold:
            return Decision(blocked, "probability_below_threshold", probability, edge)
        return Decision(
            "enter" if position is None else "hold",
            "positive_cost_adjusted_edge",
            probability,
            edge,
        )
