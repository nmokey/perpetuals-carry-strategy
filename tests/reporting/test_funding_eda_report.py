"""M6-T1 documented output: real rendering, source evidence and reproducible CLI."""

import datetime as dt
import json
import sys

import pytest

from perpcarry.ingestion import fetch_funding, funding_series
from perpcarry.models import funding_eda
from perpcarry.reporting import funding_eda as rendering
from perpcarry.tools import analyze_funding


def test_report_has_statistics_warnings_and_actual_pngs(funding_frame_factory, tmp_path):
    frame = funding_frame_factory()
    analysis = funding_eda.analyze(
        frame,
        warmup_start=dt.date(2025, 7, 1),
        study_start=dt.date(2025, 9, 1),
        study_end=dt.date(2025, 10, 3),
        config=funding_eda.Config(rolling_days=30),
    )
    report = {
        "config": {
            "warmup_start": "2025-07-01",
            "study_start": "2025-09-01",
            "study_end_exclusive": "2025-10-03",
        },
        "symbols": {"TESTUSDT": analysis},
    }
    rendering.write(report, {"TESTUSDT": frame}, tmp_path)
    assert json.loads((tmp_path / "report.json").read_text()) == report
    assert len(report["plots"]) == 3
    for name in report["plots"]:
        assert (tmp_path / name).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    markdown = (tmp_path / "report.md").read_text()
    assert "TESTUSDT" in markdown
    assert "90" in markdown
    assert "strictly before" in markdown
    assert "KPSS" in markdown and "not proof" in markdown
    assert "not causal" in json.dumps(report) or "not forecasts" in markdown
    first = (tmp_path / "report.json").read_bytes()
    rendering.write(report, {"TESTUSDT": frame}, tmp_path)
    assert (tmp_path / "report.json").read_bytes() == first


def test_markdown_preserves_clipped_pvalue_bounds():
    assert rendering._pvalue({"pvalue": 0.1, "pvalue_bound": "above_table"}) == "≥0.1"
    assert rendering._pvalue({"pvalue": 0.01, "pvalue_bound": "below_table"}) == "≤0.01"
    assert rendering._pvalue({"pvalue": 0.038}) == "0.038"


@pytest.mark.parametrize("bad_evidence", [False, True])
def test_cli_uses_configured_windows_existing_corpus_and_audit(
    isolated_data_root, funding_frame_factory, monkeypatch, tmp_path, bad_evidence
):
    root = isolated_data_root
    frame = funding_frame_factory()
    fetch_funding.store(frame, root=root)
    _, hashes = funding_series.load(root, "TESTUSDT", dt.date(2025, 7, 1), dt.date(2025, 10, 3))
    if bad_evidence:
        hashes[next(iter(hashes))] = "0" * 64
    path = root / "reports/funding-study-audit.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"TESTUSDT": {"partition_sha256": hashes}}))
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
    monkeypatch.setattr(sys, "argv", ["analyze_funding", "--config", str(config)])
    # Rendering is exercised above; capture CLI plumbing without repeating all plots.
    saved = []
    monkeypatch.setattr(
        rendering, "write", lambda report, frames, dest: saved.append((report, dest))
    )
    if bad_evidence:
        with pytest.raises(funding_series.FundingSeriesError, match="stale funding evidence"):
            analyze_funding.main()
        assert not saved
    else:
        assert analyze_funding.main() == 0
        report, destination = saved[0]
        assert destination == root / "reports/funding-eda"
        assert report["config"]["study_end_exclusive"] == "2025-10-03"
        assert report["symbols"]["TESTUSDT"]["windows"]["study"]["rows"] == 96
        assert report["provenance"]["input_sha256"]["TESTUSDT"] == hashes
        assert report["provenance"]["versions"]["statsmodels"]
        assert len(report["provenance"]["command_source_sha256"]) == 64
