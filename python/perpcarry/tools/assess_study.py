"""Probe BTC/SOL historical archive coverage without downloading full datasets."""

from __future__ import annotations

import datetime as dt
import json
import tomllib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pyarrow.parquet as pq

from perpcarry.ingestion import binance_archive, fetch_trades, tardis_archive
from perpcarry.storage import data_root

STUDY_CONFIG = Path(__file__).resolve().parents[3] / "config" / "btc-sol-study.toml"
STUDY = tomllib.loads(STUDY_CONFIG.read_text())["study"]
SYMBOLS = tuple(STUDY["symbols"])
WARMUP_START = dt.date.fromisoformat(STUDY["warmup_start"])
VOLUME_START = dt.date.fromisoformat(STUDY["volume_start"])
STUDY_START = dt.date.fromisoformat(STUDY["start"])
STUDY_END = dt.date.fromisoformat(STUDY["end"])


def targets():
    for symbol in SYMBOLS:
        for month in fetch_trades.months_between(VOLUME_START, STUDY_END):
            for dataset in ("trades", "fundingRate"):
                if dataset == "fundingRate" and month < WARMUP_START:
                    continue
                yield {
                    "symbol": symbol,
                    "date": month.isoformat(),
                    "dataset": dataset,
                    "url": binance_archive.monthly_url(dataset, symbol, month),
                }
            for venue in ("futures", "spot"):
                url = binance_archive.klines_monthly_url(symbol, month, "1m")
                if venue == "spot":
                    url = url.replace("/futures/um/", "/spot/")
                yield {
                    "symbol": symbol,
                    "date": month.isoformat(),
                    "dataset": f"{venue}_klines_1m",
                    "url": url,
                }
            for dataset in tardis_archive.DATASETS:
                if month < WARMUP_START:
                    continue
                yield {
                    "symbol": symbol,
                    "date": month.isoformat(),
                    "dataset": dataset,
                    "url": tardis_archive.dataset_url(dataset, symbol, month),
                }
        # Confirm that a regular backtest day is unavailable without access credentials.
        url = tardis_archive.dataset_url(tardis_archive.INCREMENTAL_BOOK_L2, symbol, STUDY_START)
        yield {
            "symbol": symbol,
            "date": "2025-10-02",
            "dataset": "non_sample_book",
            "url": url.replace("/2025/10/01/", "/2025/10/02/"),
        }


def main() -> int:
    with httpx.Client(timeout=30, follow_redirects=True) as client:

        def probe(target):
            try:
                with client.stream("GET", target["url"]) as response:
                    prefix = next(response.iter_bytes(64), b"")
                    result = {
                        **target,
                        "status": response.status_code,
                        "bytes": int(response.headers["content-length"])
                        if "content-length" in response.headers
                        else None,
                        "archive_magic_valid": prefix.startswith((b"PK", b"\x1f\x8b")),
                    }
            except httpx.HTTPError as error:
                result = {**target, "status": None, "error": str(error)}
            return result

        with ThreadPoolExecutor(max_workers=4) as pool:
            remote = list(pool.map(probe, targets()))
    local = []
    root = data_root()
    for dataset in ("trades", "funding", "book", "book_snapshot"):
        for symbol in SYMBOLS:
            for directory in sorted((root / dataset / f"symbol={symbol}").glob("date=*")):
                files = sorted(directory.glob("*.parquet"))
                local.append(
                    {
                        "dataset": dataset,
                        "symbol": symbol,
                        "date": directory.name.removeprefix("date="),
                        "rows": sum(pq.ParquetFile(path).metadata.num_rows for path in files),
                        "bytes": sum(path.stat().st_size for path in files),
                    }
                )
    report = {
        "assessed_at": dt.datetime.now(dt.UTC).isoformat(),
        "symbols": SYMBOLS,
        "warmup_start": str(WARMUP_START),
        "study_start": str(STUDY_START),
        "study_end": str(STUDY_END),
        "local": local,
        "remote": remote,
        "caveat": "HTTP status and magic bytes establish archive availability, not completeness",
    }
    path = root / "reports" / "btc-sol-availability.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n")
    unexpected = [
        entry
        for entry in remote
        if entry["dataset"] != "non_sample_book"
        and (entry["status"] != 200 or not entry.get("archive_magic_valid"))
    ]
    print(
        f"{len(remote)} remote probes; {len(local)} local partitions; "
        f"{len(unexpected)} missing/unverified target archives; report: {path}"
    )
    for entry in unexpected:
        print(entry)
    return 1 if unexpected else 0


if __name__ == "__main__":
    raise SystemExit(main())
