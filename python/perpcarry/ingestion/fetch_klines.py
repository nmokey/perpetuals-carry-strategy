"""Daily kline downloader — the independent volume reference for M4-T3 (D-022).

**This is a cross-check, not a study input.** M5 and M7 consume the ``trades`` corpus, so the
ADV that feeds calibration must be computed from those same rows; klines validate that
computation and do not replace it. Same reasoning as D-018's harness — validate the thing you
actually use. Deliberately minimal for that reason: one interval, daily granularity, no
completeness gate. It is not a fourth first-class dataset.

What the check catches that nothing else in this project can: **a trades ingest that silently
dropped rows.** Every existing check is internal — schema, `trade_id` contiguity, partition
dates — and all of them pass on a corpus that is merely missing data the venue had. An
independent volume total, computed by someone else from the same trades, is the first thing
here that could notice.

Two things about the source that are easy to get wrong:

* **Klines take an extra ``{interval}/`` path segment.** ``archive.daily_url`` produces a 404
  for them, and a 404 reads as "the venue has no data for that day" rather than as a wrong URL.
  ``archive.klines_daily_url`` exists for this and is used here rather than restated.
* **The CSV ships without a header row**, so column identity comes entirely from position.
  ``archive.KLINE_COLUMNS`` is the single source of that ordering; a local copy would be a
  second source of truth that can only agree by luck (C15).
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
from pathlib import Path

import httpx
import pandas as pd

from perpcarry.ingestion import binance_archive as archive
from perpcarry.ingestion.download import cached_fetch, extract_csv, fetch_checksum
from perpcarry.storage import data_root, write_parquet

log = logging.getLogger(__name__)

#: Storage directory under the data root. As with funding, deliberately not the archive's own
#: dataset word: this is where normalised rows live, not what the URL says.
STORAGE_DIR = "klines"

#: Bar interval. Daily bars are what an ADV check needs; a finer interval would be more data
#: for no additional signal here.
INTERVAL = "1d"

#: Output schema. Narrow on purpose — only the columns the cross-check reads, plus enough to
#: locate a row. Carrying all twelve archive columns would imply this dataset is for general
#: use, which D-022 explicitly says it is not.
SCHEMA: dict[str, str] = {
    "open_time": "int64",
    "symbol": "string",
    "close": "float64",
    "volume": "float64",
    "quote_volume": "float64",
    "trades": "int64",
    "date": "string",
}

PARTITION_COLS = ["symbol", "date"]


class KlineDataError(RuntimeError):
    """Downloaded klines failed a structural check."""


def normalise(raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Map the headerless archive CSV onto :data:`SCHEMA`.

    The archive has shipped klines with and without a header row over the years. Both are
    handled by detecting a non-numeric first cell, because guessing wrong silently drops a bar
    or turns the header into a row of NaNs.
    """
    if list(raw.columns) != archive.KLINE_COLUMNS:
        raise KlineDataError(
            f"kline columns changed: expected {len(archive.KLINE_COLUMNS)} positional columns, "
            f"got {list(raw.columns)}"
        )

    frame = raw
    if not frame.empty and not str(frame["open_time"].iloc[0]).strip().lstrip("-").isdigit():
        frame = frame.iloc[1:]  # a header row shipped inside the CSV

    if frame.empty:
        raise KlineDataError(f"{symbol}: kline file contained no bars")

    open_time = frame["open_time"].astype("int64")
    out = pd.DataFrame(
        {
            "open_time": open_time,
            "symbol": pd.array([symbol] * len(frame), dtype="string"),
            "close": frame["close"].astype("float64"),
            "volume": frame["volume"].astype("float64"),
            "quote_volume": frame["quote_volume"].astype("float64"),
            "trades": frame["count"].astype("int64"),
            "date": pd.to_datetime(open_time, unit="ms", utc=True)
            .dt.strftime("%Y-%m-%d")
            .astype("string"),
        }
    )
    if (out["volume"] < 0).any():
        raise KlineDataError(f"{symbol}: negative bar volume")
    return out.sort_values("open_time", ignore_index=True)


def fetch_day(
    symbol: str,
    date: dt.date | str,
    *,
    client: httpx.Client | None = None,
    verify_checksum: bool = True,
) -> pd.DataFrame:
    """Download and normalise one day of daily klines."""
    url = archive.klines_daily_url(symbol, date, interval=INTERVAL)
    digest = fetch_checksum(url, client=client) if verify_checksum else None
    path = cached_fetch(url, expected_sha256=digest, client=client)
    return normalise(extract_csv(path, dtype=str, header=None, names=archive.KLINE_COLUMNS), symbol)


def store(frame: pd.DataFrame, *, root: Path | None = None) -> Path:
    """Write normalised klines to the partitioned Parquet dataset. Idempotent."""
    dest = (root if root is not None else data_root()) / STORAGE_DIR
    return write_parquet(frame, dest, partition_cols=PARTITION_COLS)


def partition_path(symbol: str, date: dt.date | str, root: Path | None = None) -> Path:
    """Where :func:`store` puts one symbol-day.

    Exported so readers locate partitions through the writer rather than restating the layout
    — the mistake that let M1-T4's validator report a healthy corpus while looking in a
    directory that had never existed (C15).
    """
    day = dt.date.fromisoformat(date) if isinstance(date, str) else date
    base = data_root() if root is None else Path(root)
    return base / STORAGE_DIR / f"symbol={symbol}" / f"date={day.isoformat()}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--date", required=True, help="UTC date, YYYY-MM-DD")
    parser.add_argument("--no-verify", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    frame = fetch_day(args.symbol, args.date, verify_checksum=not args.no_verify)
    path = store(frame)
    log.info("%s %s: %d bar(s) -> %s", args.symbol, args.date, len(frame), path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
