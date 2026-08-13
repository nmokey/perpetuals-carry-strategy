"""PerpCarry: funding-rate-aware execution cost analysis for crypto perpetual futures."""

from perpcarry.storage import data_root, read_parquet, write_parquet

__version__ = "0.1.0"

__all__ = ["__version__", "data_root", "read_parquet", "write_parquet"]
