"""Measure one daily trade ingest and store it only after exact volume reconciliation."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import resource
import time

from perpcarry.ingestion import fetch_trades
from perpcarry.integrity import partition_fingerprint
from perpcarry.storage import data_root


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--date", required=True, type=dt.date.fromisoformat)
    args = parser.parse_args()
    started = time.perf_counter()
    frame = fetch_trades.fetch_day(args.symbol, args.date)
    ours = fetch_trades.total_quantity(frame)
    reference = fetch_trades.klines_volume(args.symbol, args.date)
    _, losses = fetch_trades.classify_gaps(fetch_trades.trade_id_gaps(frame))
    if ours != reference or losses or fetch_trades.duplicate_trade_ids(frame):
        raise fetch_trades.TradeDataError("daily ingest failed integrity/volume checks")
    fetch_trades.store(frame)
    partition = (
        data_root() / fetch_trades.STORAGE_DIR / f"symbol={args.symbol}" / f"date={args.date}"
    )
    report = {
        "symbol": args.symbol,
        "date": args.date.isoformat(),
        "rows": len(frame),
        "volume": str(ours),
        "klines_volume": str(reference),
        "seconds": round(time.perf_counter() - started, 3),
        "peak_rss_kib_linux": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "parquet_bytes": sum(path.stat().st_size for path in partition.glob("*.parquet")),
        "sha256": partition_fingerprint(partition),
    }
    path = data_root() / "reports" / f"benchmark-{args.symbol}-{args.date}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
