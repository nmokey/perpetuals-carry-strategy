"""M6-T1 inputs: coverage, original timestamps, cadence, identity and stable evidence."""

import datetime as dt

import pandas as pd
import pytest

from perpcarry.ingestion import fetch_funding, funding_series

START = dt.date(2025, 7, 1)
END = dt.date(2025, 7, 4)


@pytest.fixture
def stored(isolated_data_root, funding_frame_factory):
    frame = funding_frame_factory(str(START), str(END))
    fetch_funding.store(frame, root=isolated_data_root)
    return isolated_data_root, frame


def test_complete_window_preserves_values_times_and_dtypes(stored):
    root, expected = stored
    loaded, hashes = funding_series.load(root, "TESTUSDT", START, END)
    pd.testing.assert_frame_equal(loaded[expected.columns], expected, check_exact=True)
    assert len(hashes) == 3
    assert all(len(digest) == 64 for digest in hashes.values())
    repeated, matching = funding_series.load(root, "TESTUSDT", START, END, expected_hashes=hashes)
    pd.testing.assert_frame_equal(repeated, loaded, check_exact=True)
    assert matching == hashes


@pytest.mark.parametrize(
    "defect",
    [
        "first",
        "last",
        "middle",
        "duplicate",
        "order",
        "date",
        "symbol",
        "null",
        "infinite",
        "rate",
        "cadence",
        "dtype",
    ],
)
def test_incomplete_or_corrupt_funding_is_rejected(funding_frame_factory, defect):
    frame = funding_frame_factory(str(START), str(END))
    if defect in {"first", "last", "middle"}:
        index = {"first": 0, "last": len(frame) - 1, "middle": 4}[defect]
        frame = frame.drop(index)
    elif defect == "duplicate":
        frame = pd.concat([frame.iloc[:1], frame], ignore_index=True)
    elif defect == "order":
        frame = frame.iloc[::-1]
    elif defect == "date":
        frame.loc[0, "date"] = "2025-07-02"
    elif defect == "symbol":
        frame.loc[0, "symbol"] = "OTHERUSDT"
    elif defect in {"null", "infinite", "rate"}:
        frame.loc[0, "funding_rate"] = {
            "null": float("nan"),
            "infinite": float("inf"),
            "rate": 0.2,
        }[defect]
    elif defect == "cadence":
        frame.loc[0, "funding_interval_hours"] = 0
    else:
        frame["funding_time"] = frame.funding_time.astype(float)
    with pytest.raises(funding_series.FundingSeriesError):
        funding_series.validate(frame, START, END)


def test_missing_and_stale_source_evidence_fail(stored):
    root, _ = stored
    _, hashes = funding_series.load(root, "TESTUSDT", START, END)
    for bad in ({}, {**hashes, next(iter(hashes)): "0" * 64}):
        with pytest.raises(funding_series.FundingSeriesError, match="stale funding evidence"):
            funding_series.load(root, "TESTUSDT", START, END, expected_hashes=bad)


def test_missing_partition_fails_and_future_partitions_are_not_read(stored):
    root, _ = stored
    future = root / fetch_funding.STORAGE_DIR / "symbol=TESTUSDT/date=2026-01-01"
    future.mkdir(parents=True)
    (future / "bad.parquet").write_bytes(b"corrupt future")
    loaded, _ = funding_series.load(root, "TESTUSDT", START, END)
    assert len(loaded) == 9
    with pytest.raises(funding_series.FundingSeriesError, match="missing funding partition"):
        funding_series.load(root, "TESTUSDT", START, END + dt.timedelta(days=1))


def test_source_change_during_read_is_rejected(stored, monkeypatch):
    root, _ = stored
    original = funding_series.pq.ParquetFile

    class ChangingFile:
        def __init__(self, path):
            self.path = path

        def read(self):
            table = original(self.path).read()
            self.path.write_bytes(b"changed during read")
            return table

    monkeypatch.setattr(funding_series.pq, "ParquetFile", ChangingFile)
    with pytest.raises(funding_series.FundingSeriesError, match="changed while loading"):
        funding_series.load(root, "TESTUSDT", START, END)


def test_partition_identity_is_checked(stored):
    root, frame = stored
    frame.loc[0, "date"] = "2025-07-02"
    # Writer paths come from the writer, but contents deliberately contradict their timestamp.
    fetch_funding.store(frame, root=root)
    with pytest.raises(funding_series.FundingSeriesError):
        funding_series.load(root, "TESTUSDT", START, END)


def test_final_snapshot_rechecks_an_earlier_day(stored, monkeypatch):
    root, _ = stored
    first = next(
        (root / fetch_funding.STORAGE_DIR / "symbol=TESTUSDT" / f"date={START}").glob("*.parquet")
    )
    original = funding_series.pq.ParquetFile

    class EarlierDayChanged:
        def __init__(self, path):
            self.path = path

        def read(self):
            table = original(self.path).read()
            if self.path.parent.name == "date=2025-07-02":
                first.write_bytes(b"earlier source changed after its completed read")
            return table

    monkeypatch.setattr(funding_series.pq, "ParquetFile", EarlierDayChanged)
    with pytest.raises(funding_series.FundingSeriesError, match="selection changed"):
        funding_series.load(root, "TESTUSDT", START, END)
