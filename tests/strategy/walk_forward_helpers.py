"""Shared synthetic M7-T3 events and admitted-input fixtures; no research corpus writes."""

import datetime as dt
from decimal import Decimal

import pytest

from perpcarry.ingestion.funding_series import utc_ms
from perpcarry.models.rolling_funding import DAY_MS, HOUR_MS, RollingFundingModel
from perpcarry.strategy import costs, funding
from perpcarry.strategy import walk_forward as wf
from perpcarry.strategy.accounting import Marks
from perpcarry.strategy.carry import FundingApproval, Policy
from perpcarry.strategy.execution import (
    InferredExecutor,
)
from perpcarry.strategy.fees import FeePeriod, FeeSchedule
from perpcarry.strategy.sizing import SizingInputs

D = Decimal
START = utc_ms(dt.date(2025, 10, 1))
WARMUP = START - 30 * DAY_MS
END = utc_ms(dt.date(2025, 11, 1))
STEP = 8 * HOUR_MS


@pytest.fixture
def scenario():
    config = wf.Config(
        "BTCUSDT",
        WARMUP,
        START,
        END,
        D(10000),
        D(1),
        Policy(2, 0.8, 0.5, allow_synthetic_costs=True),
        "inferred",
        draws=128,
    )
    fees = FeeSchedule(
        tuple(
            FeePeriod(
                config.symbol,
                market,
                WARMUP,
                END,
                D(0),
                "https://example.org/synthetic",
                WARMUP,
                "assumption",
            )
            for market in ("spot", "perp")
        ),
        allow_assumptions=True,
    )
    return config, fees


def warmup():
    return [wf.FundingEvent(f"warm-{t}", t, D(".004"), 8, None) for t in range(WARMUP, START, STEP)]


def observation(t, *, rate=".004", mark="100"):
    return wf.FundingEvent(f"fund-{t}", t, D(rate), 8, D(mark))


def opportunity(config, now, *, approval=True, coefficient=20.0):
    day = now // DAY_MS * DAY_MS
    model = RollingFundingModel(
        min_settlements=config.min_settlements, rolling_days=config.rolling_days, prior=config.prior
    )
    admitted = FundingApproval(
        config.symbol, (1, 2), 8, WARMUP, END, "e" * 64, approval, funding.model_digest(model)
    )
    market = SizingInputs(
        config.symbol,
        now,
        now + HOUR_MS,
        100.0,
        1000.0,
        day - 30 * DAY_MS,
        day,
        "a" * 64,
        D(".1"),
        D(".1"),
        0.0,
        1000.0,
        0.01,
        10.0,
        WARMUP,
        END,
        "b" * 64,
    )
    curve = costs.ImpactCurve(
        config.symbol, now, START, "c" * 64, "synthetic", coefficient, 30.0, 0.0001, 0.0009
    )
    return wf.Opportunity(wf.fold_start(now), curve, admitted, market, 0.0, 2.0, 0.0)


def tick(config, now, *, opportunity_present=True, decide=True, spot="100", perp="100"):
    return wf.MarketEvent(
        f"market-{now}",
        now,
        D(spot),
        D(perp),
        Marks(config.symbol, now, D(spot), D(perp)),
        opportunity(config, now) if opportunity_present else None,
        decide,
        D(0),
    )


def stream(config, count=4):
    events = warmup()
    for t in range(START, START + count * STEP, STEP):
        events.extend([observation(t), tick(config, t + 16000)])
    return events


def run(config, fees, events, executor=None):
    return list(wf.iter_backtest(config, iter(events), fees, executor or InferredExecutor()))
