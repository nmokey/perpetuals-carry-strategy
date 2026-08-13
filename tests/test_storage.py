"""M0-T4 acceptance: write a sample frame, read it back, assert equality."""

import pandas as pd
import pyarrow.dataset as ds
import pytest
from pandas.testing import assert_frame_equal

from perpcarry.storage import DATA_ROOT_ENV_VAR, data_root, read_parquet, write_parquet


@pytest.fixture
def trades() -> pd.DataFrame:
    """A frame shaped like the trades schema in design-doc Section 3.1."""
    return pd.DataFrame(
        {
            "timestamp": [1_700_000_000_000, 1_700_000_000_500, 1_700_000_001_000],
            "trade_id": [1, 2, 3],
            "symbol": ["BTCUSDT", "BTCUSDT", "BTCUSDT"],
            "price": [37000.10, 37000.20, 36999.90],
            "quantity": [0.01, 0.25, 1.5],
            "side": ["buy", "sell", "buy"],
            "date": ["2023-11-14"] * 3,
        }
    )


def test_round_trip_single_file(tmp_path, trades):
    path = write_parquet(trades, tmp_path / "trades.parquet")

    assert_frame_equal(read_parquet(path), trades)


def test_round_trip_partitioned(tmp_path, trades):
    path = write_parquet(trades, tmp_path / "trades", partition_cols=["symbol", "date"])

    result = read_parquet(path)
    # Partition columns come back as categoricals in the order pyarrow discovers them.
    result = result.astype({"symbol": "string", "date": "string"})
    result = result[trades.columns].sort_values("trade_id").reset_index(drop=True)
    expected = trades.astype({"symbol": "string", "date": "string"})

    assert_frame_equal(result, expected)


def test_partition_filter_prunes_rows(tmp_path, trades):
    frame = pd.concat([trades, trades.assign(symbol="ETHUSDT", trade_id=[4, 5, 6])])
    path = write_parquet(frame, tmp_path / "trades", partition_cols=["symbol", "date"])

    result = read_parquet(path, filters=ds.field("symbol") == "BTCUSDT")

    assert sorted(result["trade_id"]) == [1, 2, 3]


def test_column_projection(tmp_path, trades):
    path = write_parquet(trades, tmp_path / "trades.parquet")

    result = read_parquet(path, columns=["trade_id", "price"])

    assert list(result.columns) == ["trade_id", "price"]


def test_missing_partition_column_is_rejected(tmp_path, trades):
    with pytest.raises(KeyError):
        write_parquet(trades, tmp_path / "trades", partition_cols=["venue"])


def test_read_missing_path_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_parquet(tmp_path / "nope.parquet")


def test_data_root_is_env_overridable(tmp_path, monkeypatch):
    monkeypatch.setenv(DATA_ROOT_ENV_VAR, str(tmp_path))

    assert data_root() == tmp_path
