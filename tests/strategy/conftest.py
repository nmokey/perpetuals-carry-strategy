"""Synthetic impact artifacts made through the actual M5 fit/export interfaces."""

import pandas as pd
import pytest

from perpcarry.models import impact_model, impact_model_io


@pytest.fixture
def impact_artifact_factory():
    def build(sides=("sell", "buy")):
        rows = []
        for side in sides:
            coefficient = 20.0 if side == "sell" else 30.0
            for day in ("2025-07-01", "2025-07-19", "2025-08-03"):
                for i, size in enumerate((0.0001, 0.0004, 0.0009)):
                    rows.append(
                        dict(
                            symbol="BTCUSDT",
                            date=day,
                            timestamp=int(pd.Timestamp(day, tz="UTC").timestamp() * 1000) + 137 + i,
                            side=side,
                            schedule="static",
                            adv_fraction=size,
                            slippage_vs_touch_bps=coefficient * size**0.5,
                            crossed_at_entry=False,
                            exhausted_book=False,
                            beyond_validated_depth=False,
                        )
                    )
        report = impact_model.fit(pd.DataFrame(rows), train_end="2025-08-01", test_end="2025-09-01")
        report.summary["fitting_source_sha256"] = "a" * 64
        report.summary["inputs"] = [
            dict(symbol="BTCUSDT", date=day, manifest_sha256="b" * 64)
            for day in ("2025-07-01", "2025-07-19", "2025-08-03")
        ]
        return impact_model_io.from_fit_report(
            report,
            "BTCUSDT",
            fit_date="2026-10-10",
            code_version="synthetic-test",
            kind="synthetic",
        )

    return build
