"""Bind M6 forecasts to their symbol and model/configuration scope."""

import hashlib
import json
from dataclasses import asdict

from perpcarry.integrity import sha256
from perpcarry.models import funding_model, rolling_funding
from perpcarry.models.rolling_funding import RollingFundingModel
from perpcarry.strategy.carry import FundingForecast


def model_digest(model: RollingFundingModel) -> str:
    specification = {
        "rolling_days": model.rolling_days,
        "min_settlements": model.min_settlements,
        "prior": asdict(model.prior),
        "source_sha256": {
            "funding_model": sha256(funding_model.__file__),
            "rolling_funding": sha256(rolling_funding.__file__),
        },
    }
    encoded = json.dumps(specification, sort_keys=True, allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def from_model(symbol, model, *, horizon, now_ms, draws=4096, seed=603):
    prediction = model.predict_cumulative_funding(horizon, as_of=now_ms, draws=draws, seed=seed)
    return FundingForecast(symbol, prediction, model_digest(model))
