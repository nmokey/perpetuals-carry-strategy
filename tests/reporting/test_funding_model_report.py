"""M6-T2: real report rendering and evidence-bound, warmup-only command fitting."""

import datetime as dt
import json
import sys

import numpy as np
import pytest

from perpcarry.ingestion import fetch_funding, funding_series
from perpcarry.models import funding_checks
from perpcarry.models.funding_model import fit
from perpcarry.reporting import funding_model as rendering
from perpcarry.tools import check_funding_model


def test_render_two_symbols_in_one_table_and_preserve_evidence(tmp_path):
    rates = np.array([0.1, 0.3, -0.2, 0.4, 0.5, -0.7, 0.2]) / 10_000
    model = fit(rates, interval_hours=8)
    result = {
        "posterior": model.summary(),
        "study_checks": funding_checks.check(model, rates[:-1], rates[1:]),
        "warmup_replication": funding_checks.replicate(model, rates, draws=20),
    }
    report = {"symbols": {"BTCUSDT": result, "SOLUSDT": result}, "provenance": {"hash": "test"}}
    rendering.write(report, tmp_path)
    assert json.loads((tmp_path / "report.json").read_text()) == report
    first = (tmp_path / "report.json").read_bytes()
    rendering.write(report, tmp_path)
    assert (tmp_path / "report.json").read_bytes() == first
    text = (tmp_path / "report.md").read_text()
    assert text.index("| SOLUSDT |") < text.index("## BTCUSDT")
    assert "not independent" in text and "not optimized" in text
    assert "Study negative-tail counts" in text


@pytest.mark.parametrize("condition", ["valid", "stale", "cadence"])
def test_command_frozen_warmup_no_future_leak_and_evidence(
    isolated_data_root, funding_frame_factory, monkeypatch, tmp_path, condition
):
    root = isolated_data_root
    frame = funding_frame_factory()
    fetch_funding.store(frame, root=root)
    _, hashes = funding_series.load(root, "TESTUSDT", dt.date(2025, 7, 1), dt.date(2025, 10, 3))
    if condition == "stale":
        hashes[next(iter(hashes))] = "0" * 64
    audit = root / "reports/funding-study-audit.json"
    audit.parent.mkdir()
    audit.write_text(json.dumps({"TESTUSDT": {"partition_sha256": hashes}}))
    config = tmp_path / "study.toml"
    config.write_text("""[study]
symbols = ["TESTUSDT"]
warmup_start = "2025-07-01"
start = "2025-09-01"
end = "2025-10-02"
timezone = "UTC"
data_root = "unused"
""")
    monkeypatch.setattr(sys, "argv", ["check_funding_model", "--config", str(config)])
    saved = []
    monkeypatch.setattr(rendering, "write", lambda report, dest: saved.append((report, dest)))
    # A mixed cadence must be rejected even if the loader has independently admitted it.
    if condition == "cadence":
        original = funding_series.load

        def changed(*args, **kwargs):
            admitted, evidence = original(*args, **kwargs)
            admitted.loc[admitted.index[-1], "funding_interval_hours"] = 4
            return admitted, evidence

        monkeypatch.setattr(funding_series, "load", changed)
    if condition != "valid":
        with pytest.raises(funding_series.FundingSeriesError):
            check_funding_model.main()
        assert not saved
        return
    assert check_funding_model.main() == 0
    report, destination = saved[0]
    assert destination == root / "reports/funding-model"
    first = report["symbols"]["TESTUSDT"]
    assert first["warmup_rows"] == 186 and first["posterior"]["observations"] == 185
    assert first["study_rows"] == 96 and first["study_checks"]["rows"] == 96
    assert report["provenance"]["input_sha256"]["TESTUSDT"] == hashes
    assert report["config"]["study_end_exclusive"] == "2025-10-03"
    assert report["provenance"]["versions"]["scipy"]
    # Poison study rates and refresh their admission hashes, preserving warmup byte for byte.
    selected = frame.funding_time >= funding_series.utc_ms(dt.date(2025, 9, 1))
    frame.loc[selected, "funding_rate"] = -0.002
    fetch_funding.store(frame, root=root)
    _, hashes = funding_series.load(root, "TESTUSDT", dt.date(2025, 7, 1), dt.date(2025, 10, 3))
    audit.write_text(json.dumps({"TESTUSDT": {"partition_sha256": hashes}}))
    assert check_funding_model.main() == 0
    second = saved[1][0]["symbols"]["TESTUSDT"]
    assert first["posterior"] == second["posterior"]
    assert first["warmup_replication"] == second["warmup_replication"]
    assert first["study_checks"] != second["study_checks"]
