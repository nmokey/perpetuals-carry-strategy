"""M5-T2 acceptance: synthetic laws, day separation, diagnostics and admission gates."""

from __future__ import annotations

import json
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from perpcarry.models import calibration_dataset, order_size
from perpcarry.models import impact_model as impact
from perpcarry.storage import write_parquet
from perpcarry.tools.corpus_inventory import partition_fingerprint

TRAIN_END = "2025-08-01"
TEST_END = "2025-09-02"


def data(exponent=0.5, coefficient=40.0):
    rows = []
    for day in ("2025-07-01", "2025-07-02", "2025-08-01", "2025-09-01"):
        start = int(pd.Timestamp(day, tz="UTC").timestamp() * 1000) + 137
        for i, size in enumerate(np.geomspace(1e-5, 0.1, 36)):
            rows.append(
                {
                    "symbol": "TESTUSDT",
                    "date": day,
                    "timestamp": start + i,
                    "side": "buy",
                    "schedule": "static",
                    "adv_fraction": size,
                    "slippage_vs_touch_bps": coefficient * size**exponent,
                    "slippage_vs_mid_bps": coefficient * size**exponent + 100,
                    "crossed_at_entry": False,
                    "exhausted_book": False,
                    "beyond_validated_depth": size > 0.003,
                }
            )
    return pd.DataFrame(rows)


def run(frame=None, **kwargs):
    return impact.fit(
        data() if frame is None else frame, train_end=TRAIN_END, test_end=TEST_END, **kwargs
    )


def overall(report, form="square_root", depth="inside_validated_depth", **identity):
    return next(
        r
        for r in report.summary["fits"]
        if r.get("form") == form
        and r["depth"] == depth
        and r["size_regime"] == "all_sizes"
        and all(r[key] == value for key, value in identity.items())
    )


@pytest.mark.parametrize(
    "exponent,winner,loser", [(0.5, "square_root", "linear"), (1, "linear", "square_root")]
)
def test_recovers_known_laws_without_rigging_comparison(exponent, winner, loser):
    report = run(data(exponent))
    for depth in ("inside_validated_depth", "beyond_validated_depth"):
        chosen = overall(report, winner, depth)
        assert chosen["model"]["coefficient"] == pytest.approx(40, rel=1e-14)
        assert chosen["metrics"]["test"]["r2"] == pytest.approx(1, abs=1e-14)
        assert (
            chosen["metrics"]["test"]["rmse_bps"]
            < overall(report, loser, depth)["metrics"]["test"]["rmse_bps"]
        )
        power = overall(report, "power_diagnostic", depth)
        assert power["model"]["exponent"] == pytest.approx(exponent, abs=1e-13)
    assert report.summary["primary_form"] == "square_root"


def test_held_out_targets_do_not_fit_coefficients_and_metrics_use_original_bps():
    frame = data()
    frame.loc[frame.date >= TRAIN_END, "slippage_vs_touch_bps"] += 2.75
    report = run(frame)
    fitted = overall(report)
    assert fitted["model"]["coefficient"] == pytest.approx(40, rel=1e-14)
    held = report.diagnostics.query(
        "form == 'square_root' and size_regime == 'all_sizes' "
        "and depth == 'inside_validated_depth' and split == 'test'"
    )
    expected = 1 - float((held.residual_bps**2).sum()) / float(
        ((held.observed_bps - held.observed_bps.mean()) ** 2).sum()
    )
    assert fitted["metrics"]["test"]["rmse_bps"] == pytest.approx(2.75, abs=1e-14)
    assert fitted["metrics"]["test"]["r2"] == pytest.approx(expected, abs=1e-12)
    assert expected < 0  # Poor held-out fit must not be clipped or replaced.


def test_whole_days_are_separate_and_cutoffs_have_exact_semantics():
    report = run()
    for group in report.summary["groups"]:
        assert group["train_days"] == ["2025-07-01", "2025-07-02"]
        assert group["test_days"] == ["2025-08-01", "2025-09-01"]
    assert not (
        set(report.diagnostics.query("split == 'train'").date)
        & set(report.diagnostics.query("split == 'test'").date)
    )
    end = data().query("date == '2025-09-01'").copy()
    end["date"] = TEST_END
    end["timestamp"] += 86400000
    extended = run(pd.concat([data(), end], ignore_index=True))
    pd.testing.assert_frame_equal(report.diagnostics, extended.diagnostics, check_exact=True)
    assert extended.summary["outside_window_rows"] == len(end)


def test_training_regimes_and_coefficients_ignore_future_size_poisoning():
    original = run()
    poisoned = data()
    poisoned.loc[poisoned.date >= TRAIN_END, "adv_fraction"] *= 1e6
    poisoned.loc[poisoned.date >= TRAIN_END, "slippage_vs_touch_bps"] += 999
    changed = run(poisoned)
    for depth in ("inside_validated_depth", "beyond_validated_depth"):
        before, after = overall(original, depth=depth), overall(changed, depth=depth)
        assert before["model"] == after["model"]
        assert before["size_bin_edges_adv_fraction"] == after["size_bin_edges_adv_fraction"]
        assert before["per_training_day"] == after["per_training_day"]
    assert changed.diagnostics.query("split == 'test'").outside_training_size_range.all()


def test_depth_size_and_schedule_coefficients_are_separate():
    frame = data()
    frame.loc[frame.beyond_validated_depth, "slippage_vs_touch_bps"] *= 3
    sliced = frame.assign(
        schedule="sliced", slippage_vs_touch_bps=frame.slippage_vs_touch_bps * 0.5
    )
    sell = frame.assign(side="sell", slippage_vs_touch_bps=frame.slippage_vs_touch_bps * 2)
    other = frame.assign(symbol="OTHERUSDT", slippage_vs_touch_bps=frame.slippage_vs_touch_bps * 4)
    report = run(pd.concat([frame, sliced, sell, other], ignore_index=True))
    for identities, scale in [
        ({"symbol": "TESTUSDT", "side": "buy", "schedule": "static"}, 1),
        ({"symbol": "TESTUSDT", "side": "buy", "schedule": "sliced"}, 0.5),
        ({"symbol": "TESTUSDT", "side": "sell", "schedule": "static"}, 2),
        ({"symbol": "OTHERUSDT", "side": "buy", "schedule": "static"}, 4),
    ]:
        for depth, multiplier in [("inside_validated_depth", 1), ("beyond_validated_depth", 3)]:
            record = overall(report, depth=depth, **identities)
            assert record["model"]["coefficient"] == pytest.approx(
                40 * scale * multiplier, rel=1e-14
            )
            assert record["train_rows"] == record["test_rows"] > 0
    bins = [
        r
        for r in report.summary["fits"]
        if r.get("size_regime", "").startswith("training_size_bin_")
        and r.get("form") == "square_root"
    ]
    assert len(bins) == 4 * 2 * 3


def test_crossed_and_exhausted_rows_excluded_with_union_counts():
    frame = data()
    bad = frame.iloc[:3].copy()
    bad["slippage_vs_touch_bps"] = [float("nan"), -1000, float("inf")]
    bad["crossed_at_entry"] = [False, True, True]
    bad["exhausted_book"] = [True, False, True]
    report = run(pd.concat([frame, bad], ignore_index=True))
    assert report.summary["excluded_rows"] == 3
    assert report.summary["crossed_rows"] == 2
    assert report.summary["exhausted_rows"] == 2
    assert overall(report)["status"] == "evaluated"
    assert overall(report)["model"]["coefficient"] == pytest.approx(40, rel=1e-14)
    assert report.diagnostics.observed_bps.ge(0).all()


def test_mid_relative_target_is_refused_and_mid_column_does_not_affect_fit():
    with pytest.raises(impact.ImpactModelError, match="touch-relative"):
        impact.FitConfig(target="slippage_vs_mid_bps")
    report = run()
    changed = run(data().assign(slippage_vs_mid_bps=1e9))
    assert report.summary == changed.summary
    pd.testing.assert_frame_equal(report.diagnostics, changed.diagnostics, check_exact=True)


@pytest.mark.parametrize("day", ["2025-07-01", "2025-08-01"])
def test_one_day_cannot_be_reported_as_out_of_sample(day):
    with pytest.raises(impact.ImpactModelError, match="held-out days"):
        run(data().query("date == @day"))


def test_per_training_day_coefficients_and_spread_are_reported():
    frame = data()
    frame.loc[frame.date == "2025-07-02", "slippage_vs_touch_bps"] *= 2
    report = run(frame)
    record = overall(report)
    assert [p["coefficient"] for p in record["per_training_day"]] == pytest.approx(
        [40, 80], rel=1e-14
    )
    assert record["model"]["coefficient"] == pytest.approx(60, rel=1e-14)
    assert record["daily_coefficient_std"] == pytest.approx(np.std([40, 80], ddof=1), rel=1e-14)


def test_deterministic_diagnostics_and_residual_algebra_after_shuffle():
    original, shuffled = run(), run(data().sample(frac=1, random_state=47))
    assert original.summary == shuffled.summary
    pd.testing.assert_frame_equal(original.diagnostics, shuffled.diagnostics, check_exact=True)
    np.testing.assert_array_equal(
        original.diagnostics.residual_bps,
        original.diagnostics.observed_bps - original.diagnostics.fitted_bps,
    )
    assert {"adv_fraction", "fitted_bps", "residual_bps", "split"} <= set(original.diagnostics)


def test_zero_impact_is_valid_but_constant_target_r2_and_power_are_not_fabricated():
    report = run(data().assign(slippage_vs_touch_bps=0.0))
    record = overall(report)
    assert record["model"]["coefficient"] == 0
    assert record["metrics"]["test"]["r2"] is None
    assert record["metrics"]["test"]["r2_status"] == "undefined_constant_target"
    power = overall(report, "power_diagnostic")
    assert power["status"] == "unavailable"
    assert "model" not in power


@pytest.mark.parametrize(
    "column,value",
    [
        ("adv_fraction", 0),
        ("adv_fraction", float("inf")),
        ("slippage_vs_touch_bps", float("nan")),
        ("crossed_at_entry", "False"),
        ("timestamp", 0),
    ],
)
def test_corrupt_eligible_data_fail(column, value):
    frame = data()
    if column == "crossed_at_entry":
        frame[column] = frame[column].astype(object)
    frame.loc[0, column] = value
    with pytest.raises(impact.ImpactModelError):
        run(frame)


def test_shorter_rolling_window_excludes_old_training_days():
    with pytest.raises(impact.ImpactModelError, match="held-out days"):
        run(config=replace(impact.FitConfig(), train_days=2))


def calibration_partition(root, monkeypatch):
    frame = data().query("date == '2025-07-01'")
    partition = root / "calibration/symbol=TESTUSDT/date=2025-07-01"
    write_parquet(frame, partition / "part-0.parquet")
    inputs = [{"verified": "synthetic fixture only"}]
    monkeypatch.setattr(calibration_dataset, "verified_inputs", lambda *args, **kwargs: inputs)
    manifest = {
        "task": "M5-T1",
        "symbol": "TESTUSDT",
        "date": "2025-07-01",
        "config": {},
        "rows": len(frame),
        "inputs": inputs,
        "output_sha256": partition_fingerprint(partition),
    }
    path = partition / "manifest.json"
    path.write_text(json.dumps(manifest))
    return partition, path, manifest


def test_calibration_loader_rechecks_evidence_and_records_manifest_hash(
    isolated_data_root, monkeypatch
):
    from perpcarry.ingestion.download import sha256

    _, path, _ = calibration_partition(isolated_data_root, monkeypatch)
    frame, evidence = impact.load_calibration(isolated_data_root, ["TESTUSDT"])
    assert len(frame) == 36
    assert evidence[0]["manifest_sha256"] == sha256(path)


@pytest.mark.parametrize(
    "defect", ["hash", "identity", "rows", "inputs", "missing_manifest", "quality"]
)
def test_unverified_calibration_is_refused(isolated_data_root, monkeypatch, defect):
    partition, path, manifest = calibration_partition(isolated_data_root, monkeypatch)
    if defect == "hash":
        (partition / "part-0.parquet").write_bytes(b"corrupted")
    elif defect == "identity":
        manifest["symbol"] = "WRONGUSDT"
    elif defect == "rows":
        manifest["rows"] += 1
    elif defect == "inputs":
        manifest["inputs"] = []
    elif defect == "quality":

        def reject(*args, **kwargs):
            raise order_size.OrderSizeError("rejected ADV")

        monkeypatch.setattr(calibration_dataset, "verified_inputs", reject)
    if defect == "missing_manifest":
        path.unlink()
    else:
        path.write_text(json.dumps(manifest))
    with pytest.raises((impact.ImpactModelError, order_size.OrderSizeError)):
        impact.load_calibration(isolated_data_root, ["TESTUSDT"])


def test_residual_artifacts_are_written_as_diagnostics_not_model_loader(tmp_path):
    report = run(config=impact.FitConfig(size_quantiles=()))
    (tmp_path / "residuals-999.png").write_bytes(b"obsolete figure")
    impact.write_diagnostics(report, tmp_path)
    saved = json.loads((tmp_path / "report.json").read_text())
    assert saved["primary_form"] == "square_root"
    assert (tmp_path / "residuals.parquet").exists()
    assert len(list(tmp_path.glob("*.png"))) == 6
    assert all(p.read_bytes().startswith(b"\x89PNG\r\n\x1a\n") for p in tmp_path.glob("*.png"))


def test_data_after_the_fold_cannot_poison_historical_diagnostics():
    original = run()
    future = data().query("date == '2025-09-01'").copy()
    future["date"] = "2026-01-01"
    future["timestamp"] = 0
    future["slippage_vs_touch_bps"] = float("nan")
    changed = run(pd.concat([data(), future], ignore_index=True))
    assert original.summary["fits"] == changed.summary["fits"]
    pd.testing.assert_frame_equal(original.diagnostics, changed.diagnostics, check_exact=True)


def test_fold_loader_does_not_require_future_manifests(isolated_data_root, monkeypatch):
    import datetime as dt

    calibration_partition(isolated_data_root, monkeypatch)
    future = isolated_data_root / "calibration/symbol=TESTUSDT/date=2026-01-01"
    future.mkdir()
    # Missing/corrupt future evidence cannot prevent an earlier fold from loading.
    (future / "manifest.json").write_text("corrupt future")
    frame, evidence = impact.load_calibration(
        isolated_data_root, ["TESTUSDT"], start=dt.date(2025, 7, 1), end=dt.date(2025, 8, 1)
    )
    assert len(frame) == 36
    assert [item["date"] for item in evidence] == ["2025-07-01"]


def test_cli_writes_explicit_fold_diagnostics(tmp_path, monkeypatch):
    import sys

    monkeypatch.setattr(impact, "data_root", lambda: tmp_path)
    calls = []

    def load(root, symbols, **bounds):
        calls.append((root, symbols, bounds))
        return data(), [{"synthetic": True}]

    monkeypatch.setattr(impact, "load_calibration", load)
    # Plot rendering is independently exercised above; inspect CLI report plumbing here.
    saved = []
    monkeypatch.setattr(
        impact, "write_diagnostics", lambda report, dest: saved.append((report, dest))
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["impact_model", "--symbol", "TESTUSDT", "--train-end", TRAIN_END, "--test-end", TEST_END],
    )
    assert impact.main() == 0
    assert calls[0][2]["end"].isoformat() == TEST_END
    assert saved[0][0].summary["inputs"] == [{"synthetic": True}]
    assert len(saved[0][0].summary["fitting_source_sha256"]) == 64
    assert saved[0][1].parent == tmp_path / "impact_fits"


def test_calibration_change_during_read_is_refused(isolated_data_root, monkeypatch):
    calibration_partition(isolated_data_root, monkeypatch)
    original = impact.pq.ParquetFile

    class ChangedWhileReading:
        def __init__(self, path):
            self.path = path

        def read(self):
            table = original(self.path).read()
            self.path.write_bytes(b"changed after the initial fingerprint")
            return table

    monkeypatch.setattr(impact.pq, "ParquetFile", ChangedWhileReading)
    with pytest.raises(impact.ImpactModelError, match="changed while loading"):
        impact.load_calibration(isolated_data_root, ["TESTUSDT"])


def test_power_fit_zero_exclusions_are_explicit_and_scoring_keeps_zero_rows():
    frame = data()
    frame.loc[frame.adv_fraction < 3e-5, "slippage_vs_touch_bps"] = 0
    report = run(frame)
    power = overall(report, "power_diagnostic")
    assert power["fit_rows_used"] < power["train_rows"]
    assert power["train_rows"] - power["fit_rows_used"] == power["zero_training_targets"]
    assert power["metrics"]["train"]["rows"] == power["train_rows"]
    assert power["model"]["exponent"] == pytest.approx(0.5, abs=1e-13)


def test_residuals_keep_target_and_nonconstant_fit_errors():
    frame = data()
    frame["slippage_vs_touch_bps"] += 0.4
    report = run(frame)
    residuals = report.diagnostics
    assert residuals.residual_bps.abs().max() > 0.1
    np.testing.assert_array_equal(
        residuals.residual_bps, residuals.observed_bps - residuals.fitted_bps
    )


def test_signed_sliced_slippage_is_retained_and_negative_coefficients_are_not_forced():
    frame = data().assign(schedule="sliced", slippage_vs_touch_bps=-data().slippage_vs_touch_bps)
    report = run(frame)
    fitted = overall(report)
    assert fitted["model"]["coefficient"] == pytest.approx(-40, rel=1e-14)
    assert fitted["metrics"]["test"]["r2"] == pytest.approx(1, abs=1e-14)
    assert fitted["negative_training_targets"] == fitted["train_rows"]
    assert not fitted["usable_as_nonnegative_impact_law"]
    assert report.diagnostics.observed_bps.lt(0).all()
    assert overall(report, "power_diagnostic")["status"] == "unavailable"


def test_mixed_signed_sliced_targets_are_not_silently_dropped():
    frame = data().assign(schedule="sliced")
    frame.loc[frame.adv_fraction < 3e-5, "slippage_vs_touch_bps"] *= -1
    report = run(frame)
    power = overall(report, "power_diagnostic")
    assert power["negative_training_targets"] > 0
    assert power["fit_rows_used"] + power["negative_training_targets"] == power["train_rows"]
    assert power["metrics"]["test"]["rows"] == power["test_rows"]
    assert report.diagnostics.observed_bps.lt(0).any()


def test_group_without_matching_train_test_depth_is_not_reported_as_evaluated():
    good = data()
    unmatched = good.assign(symbol="UNMATCHEDUSDT")
    unmatched["beyond_validated_depth"] = unmatched.date >= TRAIN_END
    report = run(pd.concat([good, unmatched], ignore_index=True))
    group = next(g for g in report.summary["groups"] if g["symbol"] == "UNMATCHEDUSDT")
    assert group["status"] == "no_evaluable_depth_regime"
    assert not any(
        r["status"] == "evaluated" for r in report.summary["fits"] if r["symbol"] == "UNMATCHEDUSDT"
    )


def test_static_rounding_residual_is_retained_from_the_real_simulator():
    import perpcarry_cpp as core

    replay = core.BookReplayer()
    replay.apply_batch(
        [
            core.BookUpdate(
                timestamp=1,
                local_timestamp=1,
                is_snapshot=True,
                side=core.Side.Bid,
                price=120,
                quantity=10,
            ),
            core.BookUpdate(
                timestamp=1,
                local_timestamp=1,
                is_snapshot=True,
                side=core.Side.Ask,
                price=123.45,
                quantity=10,
            ),
        ]
    )
    fill = core.simulate_market_order(replay.book(), core.OrderSide.Buy, 0.0001)
    assert fill.slippage_vs_touch_bps < 0
    frame = data()
    frame.loc[0, "slippage_vs_touch_bps"] = fill.slippage_vs_touch_bps
    report = run(frame)
    observed = report.diagnostics.loc[report.diagnostics.observed_bps < 0, "observed_bps"]
    assert len(observed) > 0
    assert (observed == fill.slippage_vs_touch_bps).all()
    assert overall(report)["negative_training_targets"] == 1
