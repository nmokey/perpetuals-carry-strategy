"""M1-T6: aligned 1m futures/spot prices, with explicit timestamp and availability rules.

Unlike fetch_klines (an ADV cross-check), these bars are research valuation inputs. Spot
archives since 2025 use microseconds; USD-M futures use milliseconds. Namespaced caches
prevent the identically named spot and futures ZIP files from replacing one another.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

from perpcarry.ingestion import binance_archive
from perpcarry.ingestion.calendar import month_bounds, months_between
from perpcarry.ingestion.download import (
    cache_dir,
    cached_fetch,
    extract_csv,
    fetch_checksum,
    sha256,
)
from perpcarry.storage import data_root, write_parquet

STORAGE_DIR = "price_bars"
PARTITION_COLS = ["market", "symbol", "date"]


class PriceDataError(RuntimeError):
    """Price archive fails a schema, coverage, timestamp or value check."""


def archive_url(symbol: str, month: dt.date, market: str) -> str:
    if market not in {"spot", "futures"}:
        raise ValueError("market must be spot or futures")
    url = binance_archive.klines_monthly_url(symbol, month, "1m")
    return url.replace("/futures/um/", "/spot/") if market == "spot" else url


def normalise(raw: pd.DataFrame, symbol: str, month: dt.date, market: str) -> pd.DataFrame:
    archive_url(symbol, month, market)  # validate the market even with synthetic data
    if list(raw.columns) != binance_archive.KLINE_COLUMNS:
        raise PriceDataError("price archive columns changed")
    raw = raw[raw["open_time"] != "open_time"]
    if raw.empty:
        raise PriceDataError("price archive has no bars")
    divisor = 1000 if market == "spot" and month >= dt.date(2025, 1, 1) else 1
    open_time = raw["open_time"].astype("int64") // divisor
    close_time = raw["close_time"].astype("int64") // divisor
    start, end = month_bounds(month)
    expected = np.arange(start, end, 60000, dtype=np.int64)
    if not np.array_equal(open_time.to_numpy(), expected):
        raise PriceDataError(
            "price archive has missing, duplicate, out-of-order or wrong-unit minutes"
        )
    if not (close_time == open_time + 59999).all():
        raise PriceDataError("price bar close time does not match its minute")
    frame = pd.DataFrame(
        {
            "open_time": open_time,
            "close_time": close_time,
            "available_at": close_time + 1,
            "market": pd.array([market] * len(raw), dtype="string"),
            "symbol": pd.array([symbol] * len(raw), dtype="string"),
            **{
                name: raw[name].astype("float64")
                for name in ("open", "high", "low", "close", "volume", "quote_volume")
            },
            "trades": raw["count"].astype("int64"),
            "date": pd.to_datetime(open_time, unit="ms", utc=True)
            .dt.strftime("%Y-%m-%d")
            .astype("string"),
        }
    )
    values = frame[["open", "high", "low", "close", "volume", "quote_volume"]]
    if not np.isfinite(values.to_numpy()).all():
        raise PriceDataError("non-finite price or volume")
    if (frame[["open", "high", "low", "close"]] <= 0).any().any():
        raise PriceDataError("non-positive price")
    if (frame[["volume", "quote_volume", "trades"]] < 0).any().any():
        raise PriceDataError("negative volume or trade count")
    if (frame["high"] < frame[["open", "close", "low"]].max(axis=1)).any() or (
        frame["low"] > frame[["open", "close", "high"]].min(axis=1)
    ).any():
        raise PriceDataError("inconsistent OHLC prices")
    return frame


def partition_path(symbol: str, date: dt.date, market: str, root: Path | None = None) -> Path:
    base = data_root() if root is None else root
    return base / STORAGE_DIR / f"market={market}" / f"symbol={symbol}" / f"date={date}"


def fetch_month(symbol: str, month: dt.date, market: str, *, client: httpx.Client | None = None):
    url = archive_url(symbol, month, market)
    checksum = fetch_checksum(url, client=client)
    if checksum is None:
        raise PriceDataError(f"no published checksum for {url}")
    path = cached_fetch(
        url,
        dest=cache_dir() / STORAGE_DIR / market / url.rsplit("/", 1)[-1],
        expected_sha256=checksum,
        client=client,
    )
    frame = normalise(
        extract_csv(path, header=None, names=binance_archive.KLINE_COLUMNS, dtype=str),
        symbol,
        month,
        market,
    )
    write_parquet(frame, data_root() / STORAGE_DIR, partition_cols=PARTITION_COLS)
    fingerprints = {
        str(file.relative_to(data_root())): sha256(file)
        for day in frame["date"].unique()
        for file in partition_path(symbol, dt.date.fromisoformat(day), market).glob("*.parquet")
    }
    report = {
        "symbol": symbol,
        "month": month.strftime("%Y-%m"),
        "market": market,
        "rows": len(frame),
        "source": url,
        "source_sha256": checksum,
        "partition_sha256": fingerprints,
        "complete_minute_grid": True,
        "timestamp_unit": "ms",
        "availability": "bar close plus 1ms",
    }
    report_path = data_root() / "reports" / f"prices-{market}-{symbol}-{month:%Y-%m}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start", type=dt.date.fromisoformat, required=True)
    parser.add_argument("--end", type=dt.date.fromisoformat, required=True)
    args = parser.parse_args()
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        for month in months_between(args.start, args.end):
            for market in ("futures", "spot"):
                report = fetch_month(args.symbol, month, market, client=client)
                print(
                    f"{args.symbol} {market} {month:%Y-%m}: {report['rows']} validated bars",
                    flush=True,
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
