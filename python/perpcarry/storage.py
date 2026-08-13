"""Parquet storage helpers (design-doc M0-T4, Section 3.4).

All datasets live as partitioned Parquet on the local filesystem under a single data
root -- ``symbol=.../date=...`` -- with no database server. DuckDB can query the same
files ad hoc for exploration.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

DEFAULT_DATA_ROOT = Path("data")
DATA_ROOT_ENV_VAR = "PERPCARRY_DATA_ROOT"

# Standard partitioning for every dataset in Section 3.
DEFAULT_PARTITION_COLS = ("symbol", "date")


def data_root() -> Path:
    """Root directory for local Parquet storage.

    Overridable via ``PERPCARRY_DATA_ROOT`` so tests and ad hoc runs can point at a
    scratch location instead of the gitignored ``data/`` directory.
    """
    return Path(os.environ.get(DATA_ROOT_ENV_VAR, DEFAULT_DATA_ROOT))


def dataset_path(name: str, root: Path | None = None) -> Path:
    """Directory holding the partitioned Parquet files for a named dataset."""
    return (root if root is not None else data_root()) / name


def write_parquet(
    df: pd.DataFrame,
    path: str | Path,
    *,
    partition_cols: Sequence[str] | None = None,
    compression: str = "zstd",
    overwrite: bool = True,
) -> Path:
    """Write ``df`` to Parquet, partitioned by ``partition_cols`` when given.

    With partition columns this writes a directory of Hive-partitioned fragments;
    without them, a single Parquet file at ``path``.
    """
    path = Path(path)
    table = pa.Table.from_pandas(df, preserve_index=False)

    if partition_cols is None:
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, path, compression=compression)
        return path

    missing = [col for col in partition_cols if col not in df.columns]
    if missing:
        raise KeyError(f"partition columns missing from frame: {missing}")

    path.mkdir(parents=True, exist_ok=True)
    pq.write_to_dataset(
        table,
        root_path=path,
        partition_cols=list(partition_cols),
        compression=compression,
        existing_data_behavior="delete_matching" if overwrite else "overwrite_or_ignore",
    )
    return path


def read_parquet(
    path: str | Path,
    *,
    columns: Sequence[str] | None = None,
    filters: ds.Expression | None = None,
) -> pd.DataFrame:
    """Read a Parquet file or partitioned dataset back into a DataFrame.

    ``filters`` takes a pyarrow dataset expression (e.g. ``ds.field("symbol") == "BTCUSDT"``)
    so partition pruning happens before anything is materialised.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)

    dataset = ds.dataset(path, format="parquet", partitioning="hive")
    table = dataset.to_table(columns=list(columns) if columns else None, filter=filters)
    return table.to_pandas()
