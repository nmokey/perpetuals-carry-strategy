"""Validate a full book day against independent snapshots and hash the exact inputs.

Raw exports and diagnostic ladders stay under the gitignored data root. Only counts,
verdicts and content hashes are written to the report.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess

from perpcarry.ingestion import fetch_book, tardis_archive
from perpcarry.integrity import partition_fingerprint
from perpcarry.storage import data_root
from perpcarry.tools import export_book


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--date", type=dt.date.fromisoformat, required=True, action="append")
    parser.add_argument("--keep-exports", action="store_true", help="retain generated raw CSVs")
    args = parser.parse_args()
    root = data_root()
    destination = root / "reports"
    destination.mkdir(parents=True, exist_ok=True)
    for day in args.date:

        def fingerprints(day=day):
            return {
                dataset: partition_fingerprint(fetch_book.partition_path(dataset, args.symbol, day))
                for dataset in tardis_archive.DATASETS
            }

        before = fingerprints()
        export = export_book.export(args.symbol, day)
        summary = export.events_path.parent / "replay.json"
        with (export.events_path.parent / "replay.log").open("w") as log:
            result = subprocess.run(
                [
                    "./build/dev/cpp/tools/perpcarry_replay_validate",
                    str(export.events_path),
                    str(export.reference_path),
                    str(summary),
                ],
                stdout=log,
                stderr=log,
                check=False,
            )
        payload = json.loads(summary.read_text()) if summary.exists() else {}
        passed = result.returncode == 0 and payload.get("passed", False)
        passed = passed and payload.get("events") == export.events and not export.truncated
        after = fingerprints()
        passed = passed and before == after
        report = {
            "symbol": args.symbol,
            "date": day.isoformat(),
            "coverage": "full day",
            "passed": passed,
            "replay": payload,
            "input_sha256": after,
        }
        path = destination / f"book-{args.symbol}-{day}.json"
        path.write_text(json.dumps(report, indent=2) + "\n")
        print(
            f"{args.symbol} {day}: {payload.get('images', 0)} images; "
            f"{'PASS' if passed else 'FAIL'}",
            flush=True,
        )
        if not passed:
            return 1
        if not args.keep_exports:
            export.events_path.unlink()
            export.reference_path.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
