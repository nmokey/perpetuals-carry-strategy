"""M6-T3: evidence-bound command, historical output isolation and truthful rendering."""

import datetime as dt
import json
import sys
from dataclasses import replace

import pytest

from perpcarry.ingestion import fetch_funding, funding_series
from perpcarry.models import funding_walk_forward
from perpcarry.reporting import rolling_funding as rendering
from perpcarry.tools import evaluate_rolling_funding


def test_rendered_report_and_repeatability(funding_frame_factory, tmp_path):
    config = funding_walk_forward.Config(rolling_days=30, horizons=(3, 21), draws=50)
    result = funding_walk_forward.analyze(
        funding_frame_factory(),
        study_start=dt.date(2025, 9, 1),
        study_end=dt.date(2025, 10, 3),
        config=config,
    )
    report = {
        "symbols": {"BTCUSDT": result, "SOLUSDT": result},
        "provenance": {"audit": "synthetic"},
    }
    rendering.write(report, tmp_path)
    assert json.loads((tmp_path / "report.json").read_text()) == report
    text = (tmp_path / "report.md").read_text()
    assert text.index("| SOLUSDT |") < text.index("## BTCUSDT")
    assert "diagnostics, not strategy" in text and "dependent" in text
    assert "2025-09" in text and "variance_scale_0.5" in text
    assert result["cumulative"]["3"]["incomplete_endpoints"] == 2
    first = (tmp_path / "report.json").read_bytes()
    rendering.write(report, tmp_path)
    assert (tmp_path / "report.json").read_bytes() == first


def test_zero_scores_are_unavailable_not_zero_coverage(tmp_path):
    result = {
        "one_step": {"rows": 0},
        "frozen_comparator": {"rows": 0},
        "monthly": {},
        "prior_sensitivity": {},
        "cumulative": {"21": {"rows": 0, "incomplete_endpoints": 0}},
    }
    rendering.write({"symbols": {"TESTUSDT": result}}, tmp_path)
    text = (tmp_path / "report.md").read_text()
    assert "| 21 | 0 | unavailable |" in text
    assert "| TESTUSDT | 0 | unavailable |" in text
    assert "0.00%" not in text


@pytest.mark.parametrize("stale", [False, True])
def test_command_uses_study_window_evidence_and_poisoned_future(
    isolated_data_root, funding_frame_factory, monkeypatch, tmp_path, stale
):
    root = isolated_data_root
    frame = funding_frame_factory()
    fetch_funding.store(frame, root=root)
    _, hashes = funding_series.load(root, "TESTUSDT", dt.date(2025, 7, 1), dt.date(2025, 10, 3))
    if stale:
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
[funding]
rolling_days = 30
""")
    monkeypatch.setattr(sys, "argv", ["evaluate_rolling_funding", "--config", str(config)])
    saved = []
    monkeypatch.setattr(rendering, "write", lambda report, dest: saved.append((report, dest)))
    original = funding_walk_forward.analyze

    def smaller(frame, **kwargs):
        kwargs["config"] = replace(kwargs["config"], draws=50)
        return original(frame, **kwargs)

    monkeypatch.setattr(funding_walk_forward, "analyze", smaller)
    if stale:
        with pytest.raises(funding_series.FundingSeriesError, match="stale"):
            evaluate_rolling_funding.main()
        assert not saved
        return
    assert evaluate_rolling_funding.main() == 0
    report, destination = saved[0]
    assert destination == root / "reports/rolling-funding"
    assert report["config"]["rolling_days"] == 30
    assert report["config"]["study_end_exclusive"] == "2025-10-03"
    assert report["provenance"]["input_sha256"]["TESTUSDT"] == hashes
    first = report["symbols"]["TESTUSDT"]["forecast_records"]
    assert len(first) == 96
    cutoff = first[9]["funding_time"]
    frame.loc[frame.funding_time >= cutoff, "funding_rate"] = -0.002
    fetch_funding.store(frame, root=root)
    _, hashes = funding_series.load(root, "TESTUSDT", dt.date(2025, 7, 1), dt.date(2025, 10, 3))
    audit.write_text(json.dumps({"TESTUSDT": {"partition_sha256": hashes}}))
    assert evaluate_rolling_funding.main() == 0
    second = saved[1][0]["symbols"]["TESTUSDT"]["forecast_records"]
    assert first[:10] == second[:10]  # cutoff value is unknown even for its own forecast
    assert first[10:] != second[10:]
