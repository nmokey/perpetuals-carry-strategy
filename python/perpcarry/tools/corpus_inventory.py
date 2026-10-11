"""Inventory stored partitions and attach content hashes to a data-quality report."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import pyarrow.parquet as pq

from perpcarry.ingestion import validate_data
from perpcarry.ingestion.book_partitions import BookPartitionError
from perpcarry.integrity import partition_fingerprint as partition_fingerprint
from perpcarry.models import calibration_dataset, order_size
from perpcarry.storage import data_root


def inventory(
    root: Path,
    *,
    reconcile_volume: bool = False,
    trades_only: bool = False,
    volume_report: dict | None = None,
) -> dict:
    corpus = validate_data.Corpus(root)
    partitions = []
    datasets = [validate_data.TRADES] if trades_only else validate_data.DATASET_DIRS
    for dataset in datasets:
        for symbol, date in corpus.partitions(dataset):
            directory = corpus.dataset_dir(dataset) / f"symbol={symbol}" / f"date={date}"
            files = sorted(directory.glob("*.parquet"))
            partitions.append(
                {
                    "dataset": dataset,
                    "symbol": symbol,
                    "date": date,
                    "rows": sum(pq.ParquetFile(path).metadata.num_rows for path in files),
                    "bytes": sum(path.stat().st_size for path in files),
                    "sha256": partition_fingerprint(directory),
                }
            )
    report = validate_data.validate(
        corpus,
        validate_data.Config(reconcile_volume=reconcile_volume),
        checks=["volume_reconciliation"] if trades_only else None,
    )
    if volume_report is not None:
        current = {
            (entry["symbol"], entry["date"]): entry["sha256"]
            for entry in partitions
            if entry["dataset"] == validate_data.TRADES
        }
        previous = {
            (entry["symbol"], entry["date"]): entry["sha256"]
            for entry in volume_report["partitions"]
            if entry["dataset"] == validate_data.TRADES
        }
        results = [
            result
            for result in volume_report["quality"]["results"]
            if result["check"] == "volume_reconciliation"
        ]
        scopes = {(result["symbol"], result["date"]) for result in results if not result["skipped"]}
        if current != previous or set(current) != scopes:
            raise validate_data.ValidationError("volume report is incomplete or stale")
        report.results = [
            result for result in report.results if result.check != "volume_reconciliation"
        ]
        report.results.extend(validate_data.CheckResult(**result) for result in results)
        reconcile_volume = True
    payload = {
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
        "reconcile_volume": reconcile_volume,
        "partitions": partitions,
        "quality": report.to_json(),
    }

    eligibility = []
    for entry in partitions:
        if entry["dataset"] != "book":
            continue
        try:
            calibration_dataset.verified_inputs(
                root,
                entry["symbol"],
                dt.date.fromisoformat(entry["date"]),
                calibration_dataset.Config(),
                report=payload,
            )
        except (order_size.OrderSizeError, BookPartitionError) as error:
            eligible, reason = False, str(error)
        else:
            eligible, reason = (
                True,
                "reconciled trades, full prior ADV window, independent book replay",
            )
        eligibility.append(
            {
                "symbol": entry["symbol"],
                "date": entry["date"],
                "eligible": eligible,
                "reason": reason,
            }
        )
    payload["calibration_eligibility"] = eligibility
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--reconcile-volume", action="store_true")
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--trades-only", action="store_true", help="reconcile stable trades while books download"
    )
    parser.add_argument(
        "--volume-report", type=Path, help="reuse reconciliation only if all trade hashes match"
    )
    args = parser.parse_args()
    root = args.root or data_root()
    if args.volume_report and args.reconcile_volume:
        parser.error("choose either --reconcile-volume or --volume-report")
    previous = json.loads(args.volume_report.read_text()) if args.volume_report else None
    report = inventory(
        root,
        reconcile_volume=args.reconcile_volume,
        trades_only=args.trades_only,
        volume_report=previous,
    )
    filename = "volume.json" if args.trades_only else "corpus.json"
    path = args.report or root / "reports" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Inventoried {len(report['partitions'])} partitions; report: {path}", flush=True)
    print(json.dumps({key: value for key, value in report["quality"].items() if key != "results"}))
    return 0 if report["quality"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
