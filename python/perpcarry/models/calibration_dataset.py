"""M5-T1: deterministic sampling of execution costs with streamed book input.

Samples the first completed exchange-millisecond group after each event-count grid point.
Busy periods therefore receive more weight. Look-ahead reads buffer future events for sliced
execution; they never enter the entry book. All dense outputs stay under the data root.
"""

from __future__ import annotations

import argparse
import datetime as dt
import itertools
import json
import math
import subprocess
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import perpcarry_cpp as core

from perpcarry.ingestion import fetch_trades, tardis_archive
from perpcarry.ingestion.book_partitions import EVENT_COLUMNS, partition_files
from perpcarry.integrity import partition_fingerprint, sha256
from perpcarry.models import order_size
from perpcarry.replay import updates_from_batch
from perpcarry.storage import data_root, iter_parquet_batches, write_parquet

FILL_FIELDS = (
    "requested_quantity",
    "filled_quantity",
    "notional",
    "average_price",
    "worst_price",
    "mid_at_entry",
    "touch_at_entry",
    "slippage_vs_mid_bps",
    "slippage_vs_touch_bps",
    "levels_consumed",
    "beyond_validated_depth",
    "crossed_at_entry",
    "exhausted_book",
)


@dataclass(frozen=True)
class Config:
    sample_every: int = 5000
    size_count: int = 40
    min_adv_fraction: float = 0.00001
    max_adv_fraction: float = 0.1
    adv_days: int = 30
    duration_ms: int = 10000
    slices: int = 5
    batch_size: int = 100000
    side: str = "buy"
    queue_capacity: int = 65536

    def __post_init__(self):
        if (
            min(self.sample_every, self.adv_days, self.slices, self.batch_size, self.queue_capacity)
            < 1
        ):
            raise ValueError("sampling, ADV, slices and batch size must be positive")
        if self.size_count < 2 or self.duration_ms < 0 or self.side not in {"buy", "sell"}:
            raise ValueError("invalid size count, duration or order side")
        if not (0 < self.min_adv_fraction < self.max_adv_fraction < float("inf")):
            raise ValueError("size fractions must be finite, positive and increasing")


def verified_inputs(
    root: Path, symbol: str, day: dt.date, config: Config, *, report: dict | None = None
) -> list[dict]:
    replay_path = root / "reports" / f"book-{symbol}-{day}.json"
    if not replay_path.exists():
        raise order_size.OrderSizeError(
            "no independent book replay report; run validate_book first"
        )
    replay = json.loads(replay_path.read_text())
    if not replay["passed"] or replay["coverage"] != "full day":
        raise order_size.OrderSizeError(f"book replay rejected: {symbol} {day}")
    for dataset in tardis_archive.DATASETS:
        directory = partition_files(dataset, symbol, day, root)[0].parent
        if partition_fingerprint(directory) != replay["input_sha256"][dataset]:
            raise order_size.OrderSizeError(f"stale book replay report: {symbol} {day}")
    if report is None:
        path = root / "reports" / "corpus.json"
        if not path.exists():
            raise order_size.OrderSizeError("no corpus quality report; run corpus_inventory first")
        report = json.loads(path.read_text())
    required = [
        (fetch_trades.STORAGE_DIR, (day - dt.timedelta(days=i)).isoformat())
        for i in range(0, config.adv_days + 1)
    ]
    required.append(("book", day.isoformat()))
    verified = []
    for dataset, date in required:
        entries = [
            entry
            for entry in report["partitions"]
            if (entry["dataset"], entry["symbol"], entry["date"]) == (dataset, symbol, date)
        ]
        directory = root / dataset / f"symbol={symbol}" / f"date={date}"
        if len(entries) != 1 or not entries[0]["sha256"]:
            raise order_size.OrderSizeError(f"unverified {dataset} partition: {symbol} {date}")
        if partition_fingerprint(directory) != entries[0]["sha256"]:
            raise order_size.OrderSizeError(f"stale quality report: {symbol} {dataset} {date}")
        checks = [
            result
            for result in report["quality"]["results"]
            if result["dataset"] == dataset
            and result["symbol"] in {None, symbol}
            and result["date"] in {None, date}
        ]
        if any(not result["passed"] and not result["skipped"] for result in checks):
            raise order_size.OrderSizeError(f"quality-rejected {dataset}: {symbol} {date}")
        if dataset == fetch_trades.STORAGE_DIR and not any(
            result["check"] == "volume_reconciliation"
            and result["date"] == date
            and result["symbol"] == symbol
            and result["passed"]
            and not result["skipped"]
            for result in checks
        ):
            raise order_size.OrderSizeError(f"volume not reconciled: {symbol} {date}")
        verified.append(entries[0])
    return [*verified, {"book_replay": replay}]


def _groups(files, batch_size):
    def updates():
        for batch in iter_parquet_batches(files, EVENT_COLUMNS, batch_size):
            yield from updates_from_batch(batch)

    for timestamp, group in itertools.groupby(updates(), key=lambda update: update.timestamp):
        yield timestamp, list(group)


def sample_rows(files, symbol: str, day: dt.date, adv: float, config: Config) -> pd.DataFrame:
    fractions = np.geomspace(config.min_adv_fraction, config.max_adv_fraction, config.size_count)
    fractions[0], fractions[-1] = config.min_adv_fraction, config.max_adv_fraction
    groups = iter(_groups(files, config.batch_size))
    pending = deque()
    pipeline = core.Pipeline(queue_capacity=config.queue_capacity)
    rows = []
    applied = 0
    replay_batch = []
    threshold = config.sample_every
    side = core.OrderSide.Buy if config.side == "buy" else core.OrderSide.Sell
    book_side = core.Side.Ask if config.side == "buy" else core.Side.Bid
    end = int(dt.datetime.combine(day + dt.timedelta(days=1), dt.time(), dt.UTC).timestamp() * 1000)
    while True:
        item = pending.popleft() if pending else next(groups, None)
        if item is None:
            break
        timestamp, updates = item
        replay_batch.extend(updates)
        applied += len(updates)
        if applied < threshold:
            continue
        pipeline.run(replay_batch)
        replayer = pipeline.replay_state()
        replay_batch.clear()
        threshold = (applied // config.sample_every + 1) * config.sample_every
        last_slice = timestamp + config.duration_ms * (config.slices - 1) // config.slices
        if last_slice >= end:
            continue
        # Read through the final slice and retain the first group beyond it. These reads
        # do not mutate the replayer. Preserve all buffered groups for the main replay.
        while not pending or pending[-1][0] <= last_slice:
            following = next(groups, None)
            if following is None:
                break
            pending.append(following)
        future = [update for time, group in pending if time <= last_slice for update in group]
        depth = sum(quantity for _, quantity in replayer.book().levels(book_side)[:25])
        for fraction in fractions:
            quantity = float(fraction * adv)
            schedule = core.SliceSchedule(timestamp, config.duration_ms, config.slices)
            static = core.simulate_market_order(replayer.book(), side, quantity)
            sliced = core.simulate_sliced_execution_from_state(
                replayer, future, side, quantity, schedule
            )
            for name, fill in (("static", static), ("sliced", sliced.parent)):
                rows.append(
                    {
                        "symbol": symbol,
                        "date": day.isoformat(),
                        "timestamp": timestamp,
                        "event_count": applied,
                        "side": config.side,
                        "schedule": name,
                        "adv": adv,
                        "adv_fraction": float(fraction),
                        "adv_percent": float(fraction * 100),
                        "depth_fraction": quantity / depth if depth > 0 else math.nan,
                        "depth_percent": quantity / depth * 100 if depth > 0 else math.nan,
                        "visible_depth_quantity": depth,
                        "completed": not fill.exhausted_book,
                        "duration_ms": config.duration_ms if name == "sliced" else 0,
                        "slice_count": config.slices if name == "sliced" else 1,
                        "slices_exhausted": (
                            sliced.slices_exhausted
                            if name == "sliced"
                            else int(fill.exhausted_book)
                        ),
                        "slices_beyond_validated_depth": (
                            sliced.slices_beyond_validated_depth
                            if name == "sliced"
                            else int(fill.beyond_validated_depth)
                        ),
                        "slices_crossed": sliced.slices_crossed
                        if name == "sliced"
                        else int(fill.crossed_at_entry),
                        **{field: getattr(fill, field) for field in FILL_FIELDS},
                    }
                )
    if not rows:
        raise ValueError("sampling produced no instants; reduce sample_every")
    if replay_batch:
        pipeline.run(replay_batch)
    if pipeline.stats().applied != applied:
        raise RuntimeError("queue replay did not consume every source event")
    frame = pd.DataFrame(rows)
    frame.attrs["events_processed"] = applied
    return frame


def generate(
    symbol: str, day: dt.date | str, *, root: Path | None = None, config: Config | None = None
) -> dict:
    day = dt.date.fromisoformat(day) if isinstance(day, str) else day
    root = data_root() if root is None else Path(root)
    config = config or Config()
    files = partition_files(tardis_archive.INCREMENTAL_BOOK_L2, symbol, day, root)
    adv = order_size.average_daily_volume(symbol, day, days=config.adv_days, root=root)
    inputs = verified_inputs(root, symbol, day, config)
    frame = sample_rows(files, symbol, day, adv, config)
    partition = root / "calibration" / f"symbol={symbol}" / f"date={day}"
    partition.mkdir(parents=True, exist_ok=True)
    # A single stable filename avoids random fragment names and duplicate partitions.
    output = partition / "part-0.parquet"
    temporary = partition / "part-0.parquet.tmp"
    write_parquet(frame, temporary)
    temporary.replace(output)
    checkout = Path(__file__).resolve().parents[3]
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=checkout, capture_output=True, text=True, check=True
    ).stdout.strip()
    sources = sorted(
        [
            *checkout.joinpath("python").rglob("*.py"),
            *checkout.joinpath("cpp").rglob("*.cpp"),
            *checkout.joinpath("cpp").rglob("*.hpp"),
            checkout / "uv.lock",
            checkout / "pyproject.toml",
        ]
    )
    manifest = {
        "task": "M5-T1",
        "symbol": symbol,
        "date": day.isoformat(),
        "config": asdict(config),
        "code_revision": revision,
        "source_sha256": {str(path.relative_to(checkout)): sha256(path) for path in sources},
        "extension_sha256": sha256(core.__file__),
        "rows": len(frame),
        "instants": frame["timestamp"].nunique(),
        "events_processed": frame.attrs["events_processed"],
        "sampling": "event-count grid rounded to the end of an exchange-millisecond group",
        "inputs": inputs,
        "output_sha256": partition_fingerprint(partition),
        "beyond_validated_depth_rows": int(frame["beyond_validated_depth"].sum()),
        "crossed_at_entry_rows": int(frame["crossed_at_entry"].sum()),
        "exhausted_book_rows": int(frame["exhausted_book"].sum()),
    }
    (partition / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--date", type=dt.date.fromisoformat, required=True, action="append")
    parser.add_argument("--sample-every", type=int, default=5000)
    parser.add_argument("--size-count", type=int, default=40)
    parser.add_argument("--side", choices=["buy", "sell"], default="buy")
    args = parser.parse_args()
    config = Config(sample_every=args.sample_every, size_count=args.size_count, side=args.side)
    for day in args.date:
        report = generate(args.symbol, day, config=config)
        print(
            f"{args.symbol} {day}: {report['rows']} rows, {report['instants']} instants", flush=True
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
