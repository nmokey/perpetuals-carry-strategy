"""M5-T3 acceptance: lossless models, provenance, caveats, strict nested schema."""

import json
import struct
from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from perpcarry.models import impact_model as impact
from perpcarry.models import impact_model_io as io


@pytest.fixture
def artifact():
    rows = []
    for symbol, coefficient in (("TESTUSDT", 12.345678901234567), ("OTHERUSDT", 75)):
        for day in ("2025-07-01", "2025-07-19", "2025-08-03"):
            for i, size in enumerate((0.000013, 0.0007, 0.0011, 0.0037)):
                rows.append(
                    dict(
                        symbol=symbol,
                        date=day,
                        timestamp=int(pd.Timestamp(day, tz="UTC").timestamp() * 1000) + i + 137,
                        side="buy",
                        schedule="static",
                        adv_fraction=size,
                        slippage_vs_touch_bps=coefficient * size**0.5,
                        crossed_at_entry=False,
                        exhausted_book=False,
                        beyond_validated_depth=size > 0.001,
                    )
                )
    report = impact.fit(pd.DataFrame(rows), train_end="2025-08-01", test_end="2025-09-01")
    report.summary["fitting_source_sha256"] = "a" * 64
    report.summary["inputs"] = [
        dict(symbol=symbol, date=day, manifest_sha256="b" * 64)
        for symbol in ("TESTUSDT", "OTHERUSDT")
        for day in ("2025-07-01", "2025-07-19", "2025-08-03")
    ]
    return io.from_fit_report(
        report, "TESTUSDT", fit_date="2026-10-09", code_version="synthetic-test", kind="synthetic"
    )


def test_bit_identical_coefficients_and_predictions(artifact, tmp_path):
    artifact["fits"][0]["model"]["coefficient"] = 12.345678901234567
    artifact["fits"][0]["model"]["exponent"] = 0.5
    path = tmp_path / "impact_TESTUSDT.json"
    io.save(artifact, path)
    loaded = io.load(path)
    assert loaded == artifact
    for before, after in zip(artifact["fits"], loaded["fits"], strict=True):
        for key in ("coefficient", "exponent"):
            assert struct.pack("!d", before["model"][key]) == struct.pack("!d", after["model"][key])
        np.testing.assert_array_equal(
            impact.FittedLaw(**before["model"]).predict([0.000021, 0.00039]),
            impact.FittedLaw(**after["model"]).predict([0.000021, 0.00039]),
        )
    assert "12.345678901234567" in path.read_text()
    previous = path.read_bytes()
    io.save(artifact, path)
    assert path.read_bytes() == previous


def test_provenance_and_caveats_are_per_symbol_and_depth_counts_survive(artifact, tmp_path):
    path = tmp_path / "model.json"
    io.save(artifact, path)
    loaded = io.load(path)
    p = loaded["provenance"]
    assert p["fit_date"] == "2026-10-09"
    assert p["code_version"] == "synthetic-test"
    assert p["fitting_source_sha256"] == "a" * 64
    assert p["corpus_days"] == ["2025-07-01", "2025-07-19", "2025-08-03"]
    assert p["supporting_train_rows"] == 8
    assert p["supporting_test_rows"] == 4
    assert {i["symbol"] for i in p["inputs"]} == {"TESTUSDT"}
    assert loaded["caveats"] == artifact["caveats"]
    assert any("year-round" in c for c in loaded["caveats"])
    assert any("Unsupported stratum" in c for c in loaded["caveats"])
    deep = [f for f in loaded["fits"] if f["depth"] == "beyond_validated_depth"]
    assert deep and all(
        f["beyond_validated_depth_rows"] == f["train_rows"] + f["test_rows"] for f in deep
    )
    assert loaded["fits"] == artifact["fits"]


@pytest.mark.parametrize("version", [0, 2, True, "1"])
def test_unknown_versions(artifact, tmp_path, version):
    artifact["schema_version"] = version
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(artifact))
    with pytest.raises(impact.ImpactModelError, match="schema version"):
        io.load(path)


@pytest.mark.parametrize(
    "location",
    [(), ("provenance",), ("fits", 0), ("fits", 0, "model"), ("provenance", "inputs", 0)],
)
@pytest.mark.parametrize("defect", ["missing", "extra"])
def test_strict_fields_at_every_level(artifact, tmp_path, location, defect):
    node = artifact
    for key in location:
        node = node[key]
    if defect == "missing":
        del node[next(iter(node))]
    else:
        node["unexpected"] = 123
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(artifact))
    with pytest.raises(impact.ImpactModelError, match="fields"):
        io.load(path)


@pytest.mark.parametrize(
    "location,value",
    [
        (("size_unit",), "percent ADV"),
        (("target",), "slippage_vs_mid_bps"),
        (("fits", 0, "model", "coefficient"), float("nan")),
        (("fits", 0, "model", "exponent"), 0.75),
        (("fits", 0, "train_rows"), True),
        (("fits", 0, "beyond_validated_depth_rows"), 999),
        (("fits", 0, "train_days"), ["2025-08-03"]),
        (("fits", 0, "usable_as_nonnegative_impact_law"), False),
        (("provenance", "corpus_days"), ["2025-07-01"]),
        (("provenance", "supporting_train_rows"), 123),
        (("provenance", "fit_date"), "invalid"),
        (("provenance", "fitting_source_sha256"), "unknown"),
    ],
)
def test_invalid_semantics_rejected_before_replacing_existing_file(
    artifact, tmp_path, location, value
):
    path = tmp_path / "model.json"
    io.save(artifact, path)
    original = path.read_bytes()
    node = artifact
    for key in location[:-1]:
        node = node[key]
    node[location[-1]] = value
    with pytest.raises(impact.ImpactModelError):
        io.save(artifact, path)
    assert path.read_bytes() == original


def test_duplicate_keys_nonfinite_numbers_and_duplicate_fits_rejected(artifact, tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"schema_version":1,"schema_version":1}')
    with pytest.raises(impact.ImpactModelError, match="duplicate JSON key"):
        io.load(path)
    artifact["fits"][0]["model"]["coefficient"] = float("inf")
    path.write_text(json.dumps(artifact))
    with pytest.raises(impact.ImpactModelError, match="non-finite"):
        io.load(path)


def test_duplicate_fit_rejected(artifact):
    artifact["fits"].append(deepcopy(artifact["fits"][0]))
    with pytest.raises(impact.ImpactModelError, match="duplicate fitted"):
        io.validate(artifact)


def test_real_export_requires_day_hash_evidence(artifact):
    artifact["provenance"]["kind"] = "verified_calibration"
    io.validate(artifact)
    artifact["provenance"]["inputs"].pop()
    with pytest.raises(impact.ImpactModelError, match="missing calibration evidence"):
        io.validate(artifact)


def test_explicit_lookup_no_fallback_and_signed_fit_retained(artifact, tmp_path):
    f = artifact["fits"][0]
    f["model"]["coefficient"] = -0.0000000000011511425447713248
    f["usable_as_nonnegative_impact_law"] = False
    io.save(artifact, tmp_path / "signed.json")
    loaded = io.load(tmp_path / "signed.json")
    params = {key: f[key] for key in ("side", "schedule", "depth", "size_regime")}
    law = io.law(loaded, **params, form=f["model"]["form"])
    assert law.coefficient == f["model"]["coefficient"]
    assert law.predict([0.01])[0] < 0
    with pytest.raises(impact.ImpactModelError, match="unavailable"):
        io.law(loaded, **{**params, "side": "sell"})


def test_fit_cli_exports_models_with_current_fitting_provenance(tmp_path, monkeypatch):
    import sys

    frame = pd.DataFrame(
        [
            dict(
                symbol="TESTUSDT",
                date=day,
                timestamp=int(pd.Timestamp(day, tz="UTC").timestamp() * 1000) + i + 137,
                side="buy",
                schedule="static",
                adv_fraction=size,
                slippage_vs_touch_bps=17 * size**0.5,
                crossed_at_entry=False,
                exhausted_book=False,
                beyond_validated_depth=False,
            )
            for day in ("2025-07-03", "2025-08-05")
            for i, size in enumerate((0.000013, 0.000071, 0.00023))
        ]
    )
    evidence = [
        dict(symbol="TESTUSDT", date=day, manifest_sha256="c" * 64) for day in frame.date.unique()
    ]
    monkeypatch.setattr(impact, "load_calibration", lambda *args, **kwargs: (frame, evidence))
    monkeypatch.setattr(impact, "data_root", lambda: tmp_path)
    saved = []
    monkeypatch.setattr(impact, "write_diagnostics", lambda report, dest: saved.append(report))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "impact_model",
            "--symbol",
            "TESTUSDT",
            "--train-end",
            "2025-08-01",
            "--test-end",
            "2025-09-01",
            "--model-dir",
            str(tmp_path / "models"),
        ],
    )
    assert impact.main() == 0
    loaded = io.load(tmp_path / "models/impact_TESTUSDT.json")
    p = loaded["provenance"]
    assert p["kind"] == "verified_calibration"
    assert p["inputs"] == evidence
    for key in ("fit_date", "code_version", "fitting_source_sha256"):
        assert p[key] == saved[0].summary[key]
    assert p["supporting_train_rows"] == 3
    assert p["supporting_test_rows"] == 3
