"""Compare daily and monthly trade archives with an independent volume reference.

Writes diagnostics only; suspect rows never enter the trades corpus.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from perpcarry.ingestion import fetch_trades
from perpcarry.storage import data_root


def investigate(symbol: str, day: dt.date) -> dict:
    monthly = fetch_trades.fetch_month(symbol, day.replace(day=1))
    selected = monthly[monthly["date"] == day.isoformat()]
    daily = fetch_trades.fetch_day(symbol, day)
    reference = fetch_trades.klines_volume(symbol, day)
    skips, losses = fetch_trades.classify_gaps(fetch_trades.trade_id_gaps(monthly))
    return {
        "symbol": symbol,
        "date": day.isoformat(),
        "monthly_rows": len(monthly),
        "monthly_small_id_gaps": len(skips),
        "monthly_large_id_gaps": len(losses),
        "monthly_first_large_id_gaps": losses[:10],
        "monthly_day_rows": len(selected),
        "daily_rows": len(daily),
        "monthly_day_volume": str(fetch_trades.total_quantity(selected)),
        "daily_volume": str(fetch_trades.total_quantity(daily)),
        "klines_volume": str(reference),
        "monthly_day_reconciles": fetch_trades.total_quantity(selected) == reference,
        "daily_reconciles": fetch_trades.total_quantity(daily) == reference,
        "daily_ids_equal_monthly": daily["trade_id"].tolist() == selected["trade_id"].tolist(),
        "daily_duplicate_ids": len(fetch_trades.duplicate_trade_ids(daily)),
        "daily_large_id_gaps": len(
            fetch_trades.classify_gaps(fetch_trades.trade_id_gaps(daily))[1]
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--date", type=dt.date.fromisoformat, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = investigate(args.symbol, args.date)
    path = args.report or data_root() / "reports" / f"trades-{args.symbol}-{args.date}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
