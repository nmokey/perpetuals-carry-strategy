"""M1-mark-prices: checksum-verified monthly mark bars, not exact settlement marks."""

from __future__ import annotations

import argparse
import calendar
import datetime as dt
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

import httpx
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from perpcarry.ingestion.binance_archive import BASE, KLINE_COLUMNS
from perpcarry.ingestion.download import cached_fetch, extract_csv, fetch_checksum
from perpcarry.integrity import sha256
from perpcarry.storage import data_root

STORAGE_DIR = "mark_prices_1m"
DATASET = "markPriceKlines"
MINUTE_MS = 60_000


class MarkPriceDataError(ValueError):
    """A source cannot be admitted as complete mark-price bars."""


def month_bounds(month: str) -> tuple[int, int]:
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise MarkPriceDataError("month must be YYYY-MM")
    start = dt.datetime.fromisoformat(month + "-01").replace(tzinfo=dt.UTC)
    end = start + dt.timedelta(days=calendar.monthrange(start.year, start.month)[1])
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def monthly_url(symbol: str, month: str) -> str:
    if symbol not in {"BTCUSDT", "SOLUSDT"}:
        raise MarkPriceDataError("research symbols are BTCUSDT/SOLUSDT")
    month_bounds(month)
    return f"{BASE}/monthly/{DATASET}/{symbol}/1m/{symbol}-1m-{month}.zip"


def normalise(raw: pd.DataFrame, symbol: str, month: str) -> pd.DataFrame:
    """Validate exact complete UTC calendar without hiding input disorder."""
    monthly_url(symbol, month)
    if list(raw.columns) != KLINE_COLUMNS:
        raise MarkPriceDataError("unexpected mark bar columns")
    frame = raw
    if not raw.empty and list(raw.iloc[0].astype(str)) == KLINE_COLUMNS:
        frame = raw.iloc[1:]
    start, end = month_bounds(month)
    if len(frame) != (end - start) // MINUTE_MS:
        raise MarkPriceDataError("missing or excess minute bars")
    try:
        opened = frame.open_time.astype("int64").reset_index(drop=True)
        closed = frame.close_time.astype("int64").reset_index(drop=True)
    except (ValueError, TypeError) as exc:
        raise MarkPriceDataError("invalid integer millisecond time") from exc
    expected = pd.Series(range(start, end, MINUTE_MS), dtype="int64")
    if not opened.equals(expected):
        raise MarkPriceDataError("minute calendar is missing, duplicated, unordered or wrong-month")
    if not closed.equals(opened + MINUTE_MS - 1):
        raise MarkPriceDataError("unexpected minute close time")
    prices: dict[str, pd.Series] = {}
    for name in ("open", "high", "low", "close"):
        values = frame[name].astype("string").reset_index(drop=True)
        try:
            parsed = values.map(Decimal)
            if not parsed.map(lambda price: price.is_finite() and price > 0).all():
                raise MarkPriceDataError("mark prices must be positive and finite")
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise MarkPriceDataError("invalid decimal mark price") from exc
        prices[name] = values
    numeric = {name: values.map(Decimal) for name, values in prices.items()}
    if (
        (numeric["low"] > numeric["open"])
        | (numeric["low"] > numeric["close"])
        | (numeric["high"] < numeric["open"])
        | (numeric["high"] < numeric["close"])
        | (numeric["low"] > numeric["high"])
    ).any():
        raise MarkPriceDataError("inconsistent mark OHLC extrema")
    return pd.DataFrame(
        {
            "open_time": opened,
            "close_time": closed,
            "available_at_ms": closed + 1,
            "symbol": pd.array([symbol] * len(frame), dtype="string"),
            **prices,
            "date": pd.to_datetime(opened, unit="ms", utc=True)
            .dt.strftime("%Y-%m-%d")
            .astype("string"),
        }
    )


def partition_path(symbol: str, day: str, root: Path | None = None) -> Path:
    base = data_root() if root is None else Path(root)
    return base / STORAGE_DIR / f"symbol={symbol}" / f"date={day}"


def store(frame: pd.DataFrame, *, root: Path) -> list[Path]:
    """One deterministic file per day, replacing only successful writes."""
    paths = []
    for (symbol, day), rows in frame.groupby(["symbol", "date"], sort=True):
        path = partition_path(symbol, day, root) / "data.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".parquet.part")
        pq.write_table(
            pa.Table.from_pandas(rows.drop(columns=["symbol", "date"]), preserve_index=False),
            temporary,
            compression="zstd",
        )
        temporary.replace(path)
        paths.append(path)
    return paths


def fetch_month(
    symbol: str, month: str, *, root: Path, client: httpx.Client | None = None
) -> tuple[pd.DataFrame, dict]:
    url = monthly_url(symbol, month)
    digest = fetch_checksum(url, client=client)
    if digest is None or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise MarkPriceDataError("published SHA-256 is required")
    # Mark and trade klines share archive basenames. Never share their cache directory.
    path = root / ".cache" / DATASET / url.rsplit("/", 1)[-1]
    cached_fetch(url, dest=path, expected_sha256=digest, client=client)
    raw = extract_csv(path, dtype=str, header=None, names=KLINE_COLUMNS)
    if not raw.empty and list(raw.iloc[0].astype(str)) == KLINE_COLUMNS:
        raw = raw.iloc[1:]
    original_rows = len(raw)
    raw, supplements = supplement_missing_days(raw, symbol, month, root=root, client=client)
    frame = normalise(raw, symbol, month)
    return frame, {
        "symbol": symbol,
        "month": month,
        "url": url,
        "sha256": digest,
        "archive_bytes": path.stat().st_size,
        "rows": len(frame),
        "first_open_ms": int(frame.open_time.iloc[0]),
        "last_available_ms": int(frame.available_at_ms.iloc[-1]),
        "monthly_rows": original_rows,
        "supplemental_daily_archives": supplements,
    }


def supplement_missing_days(
    raw: pd.DataFrame, symbol: str, month: str, *, root: Path, client: httpx.Client | None
) -> tuple[pd.DataFrame, list[dict]]:
    """Reconcile only entirely omitted days using independently checksummed archives."""
    start, end = month_bounds(month)
    expected = set(range(start, end, MINUTE_MS))
    try:
        times = list(raw.open_time.astype("int64"))
    except (ValueError, TypeError):
        return raw, []  # normalise diagnoses malformed data, rather than repairing it
    observed = set(times)
    if times != sorted(observed) or not observed <= expected:
        return raw, []
    missing = expected - observed
    if not missing:
        return raw, []
    day_ms = 86_400_000
    missing_days = sorted({value // day_ms * day_ms for value in missing})
    if any(not set(range(day, day + day_ms, MINUTE_MS)) <= missing for day in missing_days):
        return raw, []
    sources = []
    frames = [raw]
    for day in missing_days:
        date = dt.datetime.fromtimestamp(day / 1000, dt.UTC).date().isoformat()
        url = f"{BASE}/daily/{DATASET}/{symbol}/1m/{symbol}-1m-{date}.zip"
        digest = fetch_checksum(url, client=client)
        if digest is None or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise MarkPriceDataError("supplemental daily SHA-256 is required")
        path = root / ".cache" / DATASET / url.rsplit("/", 1)[-1]
        cached_fetch(url, dest=path, expected_sha256=digest, client=client)
        daily = extract_csv(path, dtype=str, header=None, names=KLINE_COLUMNS)
        if not daily.empty and list(daily.iloc[0].astype(str)) == KLINE_COLUMNS:
            daily = daily.iloc[1:]
        actual = list(daily.open_time.astype("int64"))
        if actual != list(range(day, day + day_ms, MINUTE_MS)):
            raise MarkPriceDataError("supplemental daily minute calendar mismatch")
        frames.append(daily)
        sources.append(
            {"url": url, "sha256": digest, "rows": len(daily), "archive_bytes": path.stat().st_size}
        )
    # Each source is independently ordered; only the explicit multi-source merge sorts.
    merged = pd.concat(frames, ignore_index=True)
    merged = merged.iloc[merged.open_time.astype("int64").argsort()].reset_index(drop=True)
    return merged, sources


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("data/btc-sol"))
    parser.add_argument("--start-month", default="2025-07")
    parser.add_argument("--end-month", default="2026-09")
    args = parser.parse_args(argv)
    start, _ = month_bounds(args.start_month)
    end, _ = month_bounds(args.end_month)
    if start > end:
        raise MarkPriceDataError("start month after end month")
    report_path = args.root / "reports" / "mark-prices-status.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "dataset": STORAGE_DIR,
        "kind": "mark_price_bars",
        "exact_funding_settlement_marks": False,
        "full_bar_available": "close_time + 1 ms; never expose close at open time",
        "start_month": args.start_month,
        "end_month": args.end_month,
        "archives": [],
    }
    months = pd.date_range(args.start_month + "-01", args.end_month + "-01", freq="MS")
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        for month_start in months:
            month = month_start.strftime("%Y-%m")
            for symbol in ("BTCUSDT", "SOLUSDT"):
                frame, source = fetch_month(symbol, month, root=args.root, client=client)
                files = store(frame, root=args.root)
                source["outputs"] = [
                    {
                        "path": str(path.relative_to(args.root)),
                        "sha256": sha256(path),
                        "bytes": path.stat().st_size,
                    }
                    for path in files
                ]
                report["archives"].append(source)
                temporary = report_path.with_suffix(".json.part")
                temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
                temporary.replace(report_path)
                print(f"{symbol} {month}: {len(frame)} checked minute marks", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
