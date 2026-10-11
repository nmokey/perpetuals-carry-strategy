"""M5-T1 acceptance tests. All books and volume references are synthetic."""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import replace
from decimal import Decimal

import pandas as pd
import perpcarry_cpp as core
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from perpcarry.ingestion import fetch_book, fetch_trades, tardis_archive, validate_data
from perpcarry.models import calibration_dataset as calibration
from perpcarry.models import order_size
from perpcarry.tools import corpus_inventory, export_book

DAY = dt.date(2026, 6, 1)
SYMBOL = "TESTUSDT"
START = int(dt.datetime.combine(DAY, dt.time(), dt.UTC).timestamp() * 1000) + 137
CONFIG = calibration.Config(
    sample_every=2,
    size_count=3,
    min_adv_fraction=0.001,
    max_adv_fraction=0.1,
    adv_days=2,
    duration_ms=10,
    slices=2,
    batch_size=2,
)


def book_rows():
    return {
        "exchange": ["binance-futures"] * 6,
        "timestamp": [START, START, START + 2, START + 4, START + 8, START + 20],
        "local_timestamp": [START + 1, START + 1, START + 3, START + 5, START + 9, START + 21],
        "latency_us": [1000] * 6,
        "is_snapshot": [True, True, False, False, False, False],
        "side": ["bid", "ask", "ask", "ask", "bid", "ask"],
        "price": [100.0, 101.0, 102.0, 101.0, 99.0, 102.0],
        "quantity": [100.0, 10.0, 100.0, 2.0, 0.0, 200.0],
    }


def write_book(root, rows):
    directory = fetch_book.partition_path(tardis_archive.INCREMENTAL_BOOK_L2, SYMBOL, DAY, root)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "part-0.parquet"
    pq.write_table(pa.table(rows, schema=fetch_book.SCHEMA), path)
    return [path]


def write_report(root, monkeypatch):
    monkeypatch.setattr(fetch_trades, "klines_volume", lambda symbol, date: Decimal(1000))
    report = corpus_inventory.inventory(root, reconcile_volume=True)
    path = root / "reports" / "corpus.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report))
    return report


@pytest.fixture
def corpus(isolated_data_root, monkeypatch):
    root = isolated_data_root
    write_book(root, book_rows())
    reference = {
        "exchange": ["binance-futures"] * 2,
        "timestamp": [START, START],
        "local_timestamp": [START + 1, START + 1],
        "latency_us": [1000, 1000],
        "side": ["bid", "ask"],
        "level": [0, 0],
        "price": [100.0, 101.0],
        "quantity": [100.0, 10.0],
    }
    directory = fetch_book.partition_path(tardis_archive.BOOK_SNAPSHOT_25, SYMBOL, DAY, root)
    directory.mkdir(parents=True)
    pq.write_table(
        pa.table(reference, schema=fetch_book.SNAPSHOT_SCHEMA), directory / "part-0.parquet"
    )
    raw = pd.DataFrame(
        {
            "id": [1, 2, 3],
            "price": [100.0] * 3,
            "qty": [1000.0] * 3,
            "time": [START - 2 * 86400000, START - 86400000, START],
            "is_buyer_maker": [False] * 3,
        }
    )
    fetch_trades.store(fetch_trades.normalise(raw, SYMBOL), root=root)
    report = write_report(root, monkeypatch)
    assert report["quality"]["ok"], report["quality"]
    replay = {
        "passed": True,
        "coverage": "full day",
        "input_sha256": {
            dataset: corpus_inventory.partition_fingerprint(
                fetch_book.partition_path(dataset, SYMBOL, DAY, root)
            )
            for dataset in tardis_archive.DATASETS
        },
    }
    (root / "reports" / f"book-{SYMBOL}-{DAY}.json").write_text(json.dumps(replay))
    return root


def test_deterministic_parquet_row_count_fields_and_overwrite(corpus):
    first = calibration.generate(SYMBOL, DAY, root=corpus, config=CONFIG)
    directory = corpus / "calibration" / f"symbol={SYMBOL}" / f"date={DAY}"
    original = (directory / "part-0.parquet").read_bytes()
    second = calibration.generate(SYMBOL, DAY, root=corpus, config=CONFIG)
    assert (directory / "part-0.parquet").read_bytes() == original
    assert first == second
    assert first["rows"] == first["instants"] * CONFIG.size_count * 2 == 18
    assert len(list(directory.glob("*.parquet"))) == 1
    frame = pd.read_parquet(directory / "part-0.parquet")
    assert set(calibration.FILL_FIELDS) <= set(frame.columns)
    assert frame["adv"].eq(1000.0).all()
    assert frame["adv_fraction"].min() == CONFIG.min_adv_fraction
    assert frame["adv_fraction"].max() == CONFIG.max_adv_fraction
    assert frame["adv_fraction"].unique()[1] == pytest.approx(0.01)
    assert (frame["adv_percent"] == frame["adv_fraction"] * 100).all()
    assert (frame["depth_percent"] == frame["depth_fraction"] * 100).all()


def test_sampling_is_independent_of_arrow_batch_boundaries(corpus):
    files = write_book(corpus, book_rows())
    first = calibration.sample_rows(files, SYMBOL, DAY, 1000, CONFIG)
    second = calibration.sample_rows(files, SYMBOL, DAY, 1000, replace(CONFIG, batch_size=5))
    pd.testing.assert_frame_equal(first, second, check_exact=True)


def test_queue_capacity_cannot_change_calibrated_fills(corpus):
    files = write_book(corpus, book_rows())
    first = calibration.sample_rows(files, SYMBOL, DAY, 1000, CONFIG)
    second = calibration.sample_rows(files, SYMBOL, DAY, 1000, replace(CONFIG, queue_capacity=2))
    pd.testing.assert_frame_equal(first, second, check_exact=True)
    assert first.attrs["events_processed"] == second.attrs["events_processed"] == 6


def test_static_and_sliced_fills_ignore_events_after_their_horizons(corpus):
    rows = book_rows()
    first = calibration.sample_rows(write_book(corpus, rows), SYMBOL, DAY, 1000, CONFIG)
    # Beyond the first sample's final slice at START+5.
    rows["quantity"][-1] = 9000.0
    second = calibration.sample_rows(write_book(corpus, rows), SYMBOL, DAY, 1000, CONFIG)
    select = first["timestamp"] == START
    pd.testing.assert_frame_equal(first[select], second[select], check_exact=True)
    truncated = {name: values[:4] for name, values in rows.items()}
    third = calibration.sample_rows(write_book(corpus, truncated), SYMBOL, DAY, 1000, CONFIG)
    pd.testing.assert_frame_equal(
        first[select], third[third["timestamp"] == START], check_exact=True
    )


def test_each_slice_uses_only_updates_available_by_that_slice(corpus):
    frame = calibration.sample_rows(write_book(corpus, book_rows()), SYMBOL, DAY, 1000, CONFIG)
    sample = frame[(frame["timestamp"] == START) & (frame["requested_quantity"] == 10)]
    static = sample[sample["schedule"] == "static"].iloc[0]
    sliced = sample[sample["schedule"] == "sliced"].iloc[0]
    assert static["average_price"] == 101.0
    # First 5 at 101; at t+5 only 2 remain at 101 and the other 3 cost 102.
    assert sliced["average_price"] == 101.3


def test_crossed_and_exhausted_fills_are_retained(corpus):
    rows = book_rows()
    rows["price"][0] = 103.0
    frame = calibration.sample_rows(
        write_book(corpus, rows), SYMBOL, DAY, 1000, replace(CONFIG, max_adv_fraction=1.0)
    )
    assert len(frame) == 18
    assert frame["crossed_at_entry"].all()
    assert frame["exhausted_book"].any()


def test_deep_fills_keep_the_validation_boundary_flag(corpus):
    rows = book_rows()
    for level in range(1, 30):
        extra = {
            "exchange": "binance-futures",
            "timestamp": START,
            "local_timestamp": START + 1,
            "latency_us": 1000,
            "is_snapshot": True,
            "side": "ask",
            "price": 101.0 + level,
            "quantity": 10.0,
        }
        for name, value in extra.items():
            rows[name].insert(2, value)
    frame = calibration.sample_rows(
        write_book(corpus, rows),
        SYMBOL,
        DAY,
        1000,
        replace(CONFIG, sample_every=31, max_adv_fraction=0.29, slices=1, duration_ms=0),
    )
    large = frame[frame["adv_fraction"] == 0.29]
    assert large["beyond_validated_depth"].all()
    assert (large["levels_consumed"] > 25).all()


def test_missing_book_fails(corpus):
    with pytest.raises(export_book.ExportError, match="no incremental_book_L2 partition"):
        calibration.generate(SYMBOL, DAY + dt.timedelta(days=1), root=corpus, config=CONFIG)


def test_missing_adv_day_fails(corpus):
    partition = corpus / fetch_trades.STORAGE_DIR / f"symbol={SYMBOL}" / "date=2026-05-30"
    for path in partition.glob("*.parquet"):
        path.unlink()
    partition.rmdir()
    with pytest.raises(order_size.OrderSizeError, match="missing days"):
        calibration.generate(SYMBOL, DAY, root=corpus, config=CONFIG)


@pytest.mark.parametrize("defect", ["rejected", "skipped", "stale", "missing_report"])
def test_unverified_or_rejected_adv_inputs_fail(corpus, defect):
    path = corpus / "reports" / "corpus.json"
    report = json.loads(path.read_text())
    if defect == "missing_report":
        path.unlink()
    elif defect == "stale":
        entry = next(entry for entry in report["partitions"] if entry["dataset"] == "trades")
        entry["sha256"] = {"wrong.parquet": "wrong"}
        path.write_text(json.dumps(report))
    else:
        for result in report["quality"]["results"]:
            if result["check"] == "volume_reconciliation":
                result["passed"] = defect == "skipped"
                result["skipped"] = defect == "skipped"
        path.write_text(json.dumps(report))
    with pytest.raises(order_size.OrderSizeError):
        calibration.generate(SYMBOL, DAY, root=corpus, config=CONFIG)


def test_sliced_state_copy_matches_full_replay_and_preserves_entry():
    updates = [
        core.BookUpdate(1000, is_snapshot=True, side=side, price=price, quantity=10)
        for side, price in [(core.Side.Bid, 100), (core.Side.Ask, 101)]
    ]
    # Diff followed by a resync: copying the snapshot-boundary state matters.
    updates += [
        core.BookUpdate(1001, side=core.Side.Ask, price=102, quantity=10),
        core.BookUpdate(1003, is_snapshot=True, side=core.Side.Bid, price=99, quantity=10),
        core.BookUpdate(1003, is_snapshot=True, side=core.Side.Ask, price=103, quantity=10),
    ]
    initial = core.BookReplayer()
    initial.apply_batch(updates[:3])
    before = core.dump_csv(initial.book())
    schedule = core.SliceSchedule(1001, 10, 2)
    full = core.simulate_sliced_execution(updates, core.OrderSide.Buy, 12, schedule)
    copied = core.simulate_sliced_execution_from_state(
        initial, updates[3:], core.OrderSide.Buy, 12, schedule
    )
    for field in calibration.FILL_FIELDS:
        assert getattr(full.parent, field) == getattr(copied.parent, field)
    assert core.dump_csv(initial.book()) == before
    assert copied.slices[1].average_price == 103.0
    with pytest.raises(AttributeError):
        copied.parent.filled_quantity = 0
    with pytest.raises(ValueError, match="later than"):
        core.simulate_sliced_execution_from_state(
            initial, [], core.OrderSide.Buy, 1, core.SliceSchedule(999, 10, 2)
        )


@pytest.mark.parametrize("defect", ["rejected", "stale", "missing"])
def test_book_requires_a_current_independent_replay_report(corpus, defect):
    path = corpus / "reports" / f"book-{SYMBOL}-{DAY}.json"
    if defect == "missing":
        path.unlink()
    else:
        report = json.loads(path.read_text())
        if defect == "rejected":
            report["passed"] = False
        else:
            report["input_sha256"][tardis_archive.INCREMENTAL_BOOK_L2] = {}
        path.write_text(json.dumps(report))
    with pytest.raises(order_size.OrderSizeError, match="book.*report|book replay rejected"):
        calibration.generate(SYMBOL, DAY, root=corpus, config=CONFIG)


def test_static_fill_does_not_use_updates_available_only_to_later_slices(corpus):
    rows = book_rows()
    first = calibration.sample_rows(write_book(corpus, rows), SYMBOL, DAY, 1000, CONFIG)
    rows["quantity"][3] = 40.0  # inside the first sliced window, after static entry
    second = calibration.sample_rows(write_book(corpus, rows), SYMBOL, DAY, 1000, CONFIG)
    select = (first["timestamp"] == START) & (first["schedule"] == "static")
    pd.testing.assert_frame_equal(first[select], second[select], check_exact=True)
    first_sliced = first[(first["timestamp"] == START) & (first["schedule"] == "sliced")]
    second_sliced = second[(second["timestamp"] == START) & (second["schedule"] == "sliced")]
    assert not first_sliced["average_price"].equals(second_sliced["average_price"])


def test_matching_volume_report_is_reused_without_network(corpus, monkeypatch):
    previous = corpus_inventory.inventory(corpus, trades_only=True, reconcile_volume=True)

    def forbidden(*args, **kwargs):
        raise AssertionError("reconciliation should be reused, not fetched again")

    monkeypatch.setattr(fetch_trades, "klines_volume", forbidden)
    current = corpus_inventory.inventory(corpus, volume_report=previous)
    assert current["quality"]["ok"]
    # This fixture has two prior days; the inventory uses the research default of 30.
    assert not current["calibration_eligibility"][0]["eligible"]
    assert "unverified trades partition" in current["calibration_eligibility"][0]["reason"]


@pytest.mark.parametrize("defect", ["hash", "scope", "failed"])
def test_reused_volume_evidence_cannot_hide_a_defect(corpus, defect):
    previous = corpus_inventory.inventory(corpus, trades_only=True, reconcile_volume=True)
    if defect == "hash":
        previous["partitions"][0]["sha256"] = {}
    elif defect == "scope":
        previous["quality"]["results"].pop()
    else:
        previous["quality"]["results"][0]["passed"] = False
    if defect == "failed":
        current = corpus_inventory.inventory(corpus, volume_report=previous)
        assert not current["quality"]["ok"]
        assert not current["calibration_eligibility"][0]["eligible"]
    else:
        with pytest.raises(validate_data.ValidationError, match="incomplete or stale"):
            corpus_inventory.inventory(corpus, volume_report=previous)


def test_bar_adv_opt_in_keeps_books_but_drops_unused_trade_requirement(corpus, monkeypatch):
    import shutil

    from perpcarry.models import bar_volume

    root = corpus
    shutil.rmtree(root / fetch_trades.STORAGE_DIR)
    config = replace(CONFIG, adv_source="futures_bars", adv_days=30)
    feature = {
        "method": bar_volume.METHOD,
        "symbol": SYMBOL,
        "base_adv": "2000.125",
        "adv_start_ms": START - 137 - 30 * 86400000,
        "adv_end_exclusive_ms": START - 137,
        "evidence_sha256": "b" * 64,
    }
    monkeypatch.setattr(
        bar_volume, "verified_volume_inputs", lambda root, symbol, day: {"adv": feature}
    )
    manifest = calibration.generate(SYMBOL, DAY, root=root, config=config)
    assert manifest["config"]["adv_source"] == "futures_bars"
    assert manifest["inputs"][-1] == {"adv": feature}
    assert calibration.verified_inputs(root, SYMBOL, DAY, config) == manifest["inputs"]
    from perpcarry.models import impact_model

    loaded, evidence = impact_model.load_calibration(root, [SYMBOL])
    assert len(loaded) == manifest["rows"]
    assert evidence[0]["symbol"] == SYMBOL
    feature["evidence_sha256"] = "c" * 64
    with pytest.raises(impact_model.ImpactModelError, match="input evidence changed"):
        impact_model.load_calibration(root, [SYMBOL])
    feature["evidence_sha256"] = "b" * 64
    frame = pd.read_parquet(
        root / "calibration" / f"symbol={SYMBOL}" / f"date={DAY}" / "part-0.parquet"
    )
    assert (frame["adv"] == 2000.125).all()
    with pytest.raises(order_size.OrderSizeError):
        calibration.generate(SYMBOL, DAY, root=root, config=CONFIG)
    replay_path = root / "reports" / f"book-{SYMBOL}-{DAY}.json"
    replay = json.loads(replay_path.read_text())
    replay["passed"] = False
    replay_path.write_text(json.dumps(replay))
    with pytest.raises(order_size.OrderSizeError, match="book replay rejected"):
        calibration.generate(SYMBOL, DAY, root=root, config=config)
