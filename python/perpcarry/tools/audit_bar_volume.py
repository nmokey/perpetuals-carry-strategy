"""Validate cached futures-bar volume, report trade cross-checks, and write ADV evidence."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from decimal import Decimal, localcontext
from pathlib import Path

from perpcarry.ingestion.calendar import months_between
from perpcarry.integrity import sha256
from perpcarry.models import bar_volume


def audit(root: Path, symbol: str, start: dt.date, end: dt.date) -> dict:
    days = [
        row
        for month in months_between(start, end)
        for row in bar_volume.monthly_volumes(root, symbol, month)
        if start.isoformat() <= row["date"] <= end.isoformat()
    ]
    expected = [
        (start + dt.timedelta(days=offset)).isoformat() for offset in range((end - start).days + 1)
    ]
    if [row["date"] for row in days] != expected:
        raise bar_volume.BarVolumeError("missing or duplicate audited UTC days")
    result = {
        "method": bar_volume.METHOD,
        "symbol": symbol,
        "market": "futures",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "days": days,
        "raw_trade_default_changed": False,
        "cross_checks": [],
    }
    indexed = {row["date"]: row for row in days}
    for prefix in ("benchmark", "trades"):
        for path in sorted((root / "reports").glob(f"{prefix}-{symbol}-*.json")):
            record = json.loads(path.read_text())
            if record["date"] not in indexed:
                continue
            quantity = record["volume"] if prefix == "benchmark" else record["daily_volume"]
            with localcontext() as context:
                context.prec = 60
                difference = Decimal(indexed[record["date"]]["base_volume"]) - Decimal(quantity)
            result["cross_checks"].append(
                {
                    "date": record["date"],
                    "trade_volume": quantity,
                    "bar_volume": indexed[record["date"]]["base_volume"],
                    "difference_base_units": format(difference, "f"),
                    "exact_match": difference == 0,
                    "previous_trade_admission": prefix == "benchmark"
                    or record.get("admitted", False),
                    "trade_report": str(path.relative_to(root)),
                    "trade_report_sha256": sha256(path),
                    "fresh_raw_trade_reconciliation": False,
                }
            )
    result["limitations"] = [
        "Pilot comparison uses existing hashed exact-volume reports, not fresh full trade replay.",
        "Bar source completeness does not admit rejected raw trades "
        "or prove all volume totals correct.",
        "Historical archive checksums establish reproducibility, not publication-time latency.",
    ]
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--symbol", choices=["BTCUSDT", "SOLUSDT"], required=True)
    parser.add_argument("--start", type=dt.date.fromisoformat, default=dt.date(2025, 6, 1))
    parser.add_argument("--end", type=dt.date.fromisoformat, default=dt.date(2026, 9, 30))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = audit(args.root, args.symbol, args.start, args.end)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(
        f"{args.symbol}: {len(report['days'])} exact-volume days; "
        f"{len(report['cross_checks'])} recorded trade cross-checks"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
