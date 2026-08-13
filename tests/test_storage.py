"""M0-T4 acceptance: write a sample frame, read it back, assert equality.

Equality here means *exact*: same values bit-for-bit, same dtypes, same rows. Parquet is
lossless for these types, so anything weaker would let a silent precision or dtype
regression through — and every dataset in design-doc Section 3 flows through this layer.

Two deviations are known and asserted explicitly rather than being smoothed over:
partitioned reads move partition columns to the end of the frame, and do not preserve row
order across fragments.
"""

import pandas as pd
import pyarrow.dataset as ds
import pytest
from pandas.testing import assert_frame_equal

from perpcarry.storage import (
    DATA_ROOT_ENV_VAR,
    data_root,
    dataset_path,
    read_parquet,
    write_parquet,
)

PARTITION_COLS = ["symbol", "date"]


@pytest.fixture
def trades() -> pd.DataFrame:
    """A frame shaped like the trades schema in design-doc Section 3.1."""
    return pd.DataFrame(
        {
            "timestamp": [1_700_000_000_000, 1_700_000_000_500, 1_700_000_001_000],
            "trade_id": [1, 2, 3],
            "symbol": ["BTCUSDT", "BTCUSDT", "BTCUSDT"],
            # Deliberately awkward float64 values: a lossy round trip (e.g. a silent
            # downcast to float32) changes these, an exact one does not.
            "price": [37000.123456789, 0.1 + 0.2, 1e-12],
            "quantity": [0.01, 0.25, 1.5],
            "side": ["buy", "sell", "buy"],
            "date": ["2023-11-14"] * 3,
        }
    )


def assert_exactly_equal(result: pd.DataFrame, expected: pd.DataFrame) -> None:
    """Frame equality with every tolerance switched off.

    ``assert_frame_equal`` defaults to ``check_exact=False`` (rtol 1e-5 for floats), which
    is the wrong default for a round trip: it would pass a storage layer that quietly
    perturbed prices in the fifth significant figure.
    """
    assert_frame_equal(result, expected, check_exact=True, check_dtype=True)


def test_round_trip_single_file(tmp_path, trades):
    path = write_parquet(trades, tmp_path / "trades.parquet")

    assert_exactly_equal(read_parquet(path), trades)


def test_round_trip_partitioned(tmp_path, trades):
    path = write_parquet(trades, tmp_path / "trades", partition_cols=PARTITION_COLS)

    result = read_parquet(path)

    # Deviation 1: partition columns are moved to the end of the frame. Asserted rather
    # than silently corrected, so a change in that behaviour fails here loudly.
    assert list(result.columns) == ["timestamp", "trade_id", "price", "quantity", "side"] + (
        PARTITION_COLS
    )
    # Deviation 2: row order is not preserved across fragments, so sort before comparing.
    result = result[trades.columns].sort_values("trade_id").reset_index(drop=True)

    # No dtype coercion: dtypes must survive the partitioned round trip untouched.
    assert_exactly_equal(result, trades)


def test_dtypes_survive_both_paths(tmp_path, trades):
    """Dtype preservation, asserted directly rather than only via assert_frame_equal."""
    flat = read_parquet(write_parquet(trades, tmp_path / "flat.parquet"))
    partitioned = read_parquet(
        write_parquet(trades, tmp_path / "part", partition_cols=PARTITION_COLS)
    )

    assert flat.dtypes.to_dict() == trades.dtypes.to_dict()
    assert partitioned.dtypes[trades.columns].to_dict() == trades.dtypes.to_dict()


def test_partitioned_layout_is_hive(tmp_path, trades):
    """Section 3.4 specifies ``symbol=.../date=...`` on disk, not just readable output."""
    path = write_parquet(trades, tmp_path / "trades", partition_cols=PARTITION_COLS)

    dirs = sorted(str(p.relative_to(path)) for p in path.rglob("*") if p.is_dir())

    assert dirs == ["symbol=BTCUSDT", "symbol=BTCUSDT/date=2023-11-14"]
    assert list(path.rglob("*.parquet")), "no parquet fragments written"


def test_rewrite_is_idempotent_when_overwriting(tmp_path, trades):
    """Re-running an ingestion for a date must not double the rows in that partition."""
    path = tmp_path / "trades"
    write_parquet(trades, path, partition_cols=PARTITION_COLS)
    write_parquet(trades, path, partition_cols=PARTITION_COLS, overwrite=True)

    result = read_parquet(path)[trades.columns].sort_values("trade_id").reset_index(drop=True)

    assert_exactly_equal(result, trades)


def test_rewrite_appends_when_not_overwriting(tmp_path, trades):
    """``overwrite=False`` accumulates fragments -- the caller owns deduplication."""
    path = tmp_path / "trades"
    write_parquet(trades, path, partition_cols=PARTITION_COLS, overwrite=False)
    write_parquet(trades, path, partition_cols=PARTITION_COLS, overwrite=False)

    assert len(read_parquet(path)) == 2 * len(trades)


def test_partition_filter_prunes_rows(tmp_path, trades):
    frame = pd.concat([trades, trades.assign(symbol="ETHUSDT", trade_id=[4, 5, 6])])
    path = write_parquet(frame, tmp_path / "trades", partition_cols=PARTITION_COLS)

    result = read_parquet(path, filters=ds.field("symbol") == "BTCUSDT")

    assert sorted(result["trade_id"]) == [1, 2, 3]
    assert set(result["symbol"]) == {"BTCUSDT"}


def test_column_projection(tmp_path, trades):
    path = write_parquet(trades, tmp_path / "trades.parquet")

    result = read_parquet(path, columns=["trade_id", "price"])

    assert list(result.columns) == ["trade_id", "price"]
    assert_exactly_equal(result, trades[["trade_id", "price"]])


def test_missing_partition_column_is_rejected(tmp_path, trades):
    with pytest.raises(KeyError, match="venue"):
        write_parquet(trades, tmp_path / "trades", partition_cols=["venue"])


def test_read_missing_path_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_parquet(tmp_path / "nope.parquet")


def test_data_root_is_env_overridable(tmp_path, monkeypatch):
    monkeypatch.setenv(DATA_ROOT_ENV_VAR, str(tmp_path))

    assert data_root() == tmp_path
    assert dataset_path("trades") == tmp_path / "trades"


def test_dataset_path_accepts_explicit_root(tmp_path):
    assert dataset_path("funding", root=tmp_path) == tmp_path / "funding"
