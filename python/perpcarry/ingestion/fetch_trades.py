"""Historical trades downloader (design-doc M1-T1).

Pulls the archive's ``trades`` dataset -- deliberately *not* ``aggTrades``, whose IDs are
aggregation indices with gaps by design, so the "``trade_id`` contiguous" criterion only
holds for the raw dataset.

The one subtlety worth reading before changing anything here: ``is_buyer_maker`` is *not*
the aggressor side. A resting buyer means the aggressor was the **seller**, so
``is_buyer_maker == True`` maps to ``side == "sell"``. Inverting it flips the sign of
every trade downstream and nothing raises.
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import httpx
import pandas as pd

from perpcarry.ingestion import binance_archive as archive
from perpcarry.ingestion.download import DownloadError, cached_fetch, extract_csv, fetch_checksum
from perpcarry.storage import data_root, write_parquet

log = logging.getLogger(__name__)

DATASET = "trades"

#: Output schema, per design doc Section 3.1 (plus the ``date`` partition key).
SCHEMA: dict[str, str] = {
    "timestamp": "int64",
    "trade_id": "int64",
    "symbol": "string",
    "price": "float64",
    "quantity": "float64",
    "side": "string",
    "date": "string",
}

PARTITION_COLS = ["symbol", "date"]


class TradeDataError(RuntimeError):
    """Downloaded trades failed a structural check."""


def _to_bool(values: pd.Series) -> pd.Series:
    """Coerce the archive's ``is_buyer_maker`` column to real booleans.

    The CSV is read with ``dtype=str`` to keep numeric precision exact, which makes this
    column the *strings* ``"true"``/``"false"`` -- and ``bool("false")`` is ``True``.
    Calling ``.astype(bool)`` therefore marks every trade a sell, silently and uniformly.
    Parse explicitly and reject anything unrecognised.
    """
    if values.dtype == bool:
        return values

    mapped = values.astype("string").str.strip().str.lower().map({"true": True, "false": False})
    if mapped.isna().any():
        bad = sorted(set(values[mapped.isna()].astype(str)))[:5]
        raise TradeDataError(f"unparseable is_buyer_maker values: {bad}")
    return mapped.astype(bool)


def normalise(raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Map archive columns onto the Section 3.1 schema.

    ``date`` is derived from the UTC day of each trade rather than the requested date, so
    monthly archives split into correct daily partitions and a stray out-of-day row cannot
    be silently filed under the wrong date.
    """
    missing = {"id", "price", "qty", "time", "is_buyer_maker"} - set(raw.columns)
    if missing:
        raise TradeDataError(f"archive schema changed: missing columns {sorted(missing)}")

    timestamp = raw["time"].astype("int64")
    frame = pd.DataFrame(
        {
            "timestamp": timestamp,
            "trade_id": raw["id"].astype("int64"),
            "symbol": pd.array([symbol] * len(raw), dtype="string"),
            "price": raw["price"].astype("float64"),
            "quantity": raw["qty"].astype("float64"),
            # is_buyer_maker=True -> the buyer was resting -> the aggressor sold.
            "side": pd.array(
                ["sell" if maker else "buy" for maker in _to_bool(raw["is_buyer_maker"])],
                dtype="string",
            ),
            "date": pd.to_datetime(timestamp, unit="ms", utc=True)
            .dt.strftime("%Y-%m-%d")
            .astype("string"),
        }
    )
    return frame.sort_values("trade_id", ignore_index=True)


def trade_id_gaps(frame: pd.DataFrame) -> list[tuple[int, int]]:
    """Return ``(previous_id, next_id)`` for each break in the ``trade_id`` sequence.

    Empty list means contiguous. Duplicates are *not* reported here -- they are a
    different defect with a different cause (an overlapping re-fetch rather than lost
    data), so reporting them as "gaps" would misdirect whoever reads the error. See
    :func:`duplicate_trade_ids`.
    """
    ids = frame["trade_id"].to_numpy()
    if ids.size < 2:
        return []
    diffs = ids[1:] - ids[:-1]
    return [(int(ids[i]), int(ids[i + 1])) for i in (diffs > 1).nonzero()[0]]


def duplicate_trade_ids(frame: pd.DataFrame) -> list[int]:
    """Trade IDs appearing more than once -- the signature of an overlapping re-fetch."""
    ids = frame["trade_id"]
    return sorted(int(i) for i in ids[ids.duplicated()].unique())


def total_quantity(frame: pd.DataFrame) -> Decimal:
    """Sum of traded quantity, independent of float summation order.

    The reconciliation against klines is an equality rather than a tolerance (measured
    zero difference across three symbols including 1.9M fractional-quantity trades), so
    the sum must not depend on the order floats are added in -- hence ``Decimal``.

    Note what this is *not*: the values have already been through ``float64`` in
    :func:`normalise`, so ``Decimal(str(q))`` reconstructs each float exactly but cannot
    recover precision the CSV had and ``float64`` could not hold. That is fine for
    exchange quantities (≤8 decimal places, exactly representable at these magnitudes)
    and is the reason the measured reconciliation is exact -- but it is a property of the
    data, not a guarantee of this function.
    """
    return sum((Decimal(str(q)) for q in frame["quantity"]), Decimal(0))


def klines_volume(
    symbol: str, date: dt.date | str, *, client: httpx.Client | None = None
) -> Decimal:
    """Summed 1m klines volume for the day -- the independent cross-source check."""
    url = archive.klines_daily_url(symbol, date)
    # Verified like any other archive download: a corrupt klines file would otherwise
    # surface as a spurious reconciliation *failure*, sending the reader after the trades.
    digest = fetch_checksum(url, client=client)
    path = cached_fetch(url, expected_sha256=digest, client=client)
    frame = extract_csv(path, header=None, names=archive.KLINE_COLUMNS, dtype=str)
    # Some archive files carry a header row; drop it if present.
    frame = frame[frame["volume"] != "volume"]
    return sum((Decimal(v) for v in frame["volume"]), Decimal(0))


def fetch_day(
    symbol: str,
    date: dt.date | str,
    *,
    client: httpx.Client | None = None,
    verify_checksum: bool = True,
) -> pd.DataFrame:
    """Download and normalise one day of trades. Does not write anything."""
    url = archive.daily_url(DATASET, symbol, date)
    digest = fetch_checksum(url, client=client) if verify_checksum else None
    path = cached_fetch(url, expected_sha256=digest, client=client)
    return normalise(extract_csv(path, dtype=str), symbol)


def fetch_month(
    symbol: str,
    month: dt.date | str,
    *,
    client: httpx.Client | None = None,
    verify_checksum: bool = True,
) -> pd.DataFrame:
    """Download and normalise one month of trades.

    Preferred for backfill: 24 requests per symbol instead of ~730.
    """
    url = archive.monthly_url(DATASET, symbol, month)
    digest = fetch_checksum(url, client=client) if verify_checksum else None
    path = cached_fetch(url, expected_sha256=digest, client=client)
    return normalise(extract_csv(path, dtype=str), symbol)


def store(frame: pd.DataFrame, *, root: Path | None = None) -> Path:
    """Write normalised trades to the partitioned Parquet dataset.

    Idempotent: ``write_parquet`` defaults to ``delete_matching``, so re-running a date
    replaces its partition rather than appending to it.
    """
    dest = (root if root is not None else data_root()) / DATASET
    return write_parquet(frame, dest, partition_cols=PARTITION_COLS)


def months_between(start: dt.date, end: dt.date) -> Iterator[dt.date]:
    """First-of-month dates covering ``[start, end]``."""
    cursor = start.replace(day=1)
    while cursor <= end:
        yield cursor
        cursor = (cursor.replace(day=28) + dt.timedelta(days=4)).replace(day=1)


def backfill(
    symbol: str,
    start: dt.date,
    end: dt.date,
    *,
    root: Path | None = None,
    client: httpx.Client | None = None,
    allow_missing: bool = False,
) -> list[dt.date]:
    """Fetch and store whole months over ``[start, end]``. Returns the months skipped.

    A 404 usually means the symbol was not yet listed -- ``0GUSDT`` does not exist before
    its listing date, for instance. That is an explainable gap rather than a failure, but
    it is only skipped when ``allow_missing`` is set, so it cannot pass unnoticed by
    default.
    """
    skipped: list[dt.date] = []
    previous_last_id: int | None = None

    for month in months_between(start, end):
        try:
            frame = fetch_month(symbol, month, client=client)
        except DownloadError:
            if not allow_missing:
                raise
            log.warning("no %s archive for %s %s -- skipping", DATASET, symbol, month)
            skipped.append(month)
            # The sequence is legitimately broken by the skip, so don't report the
            # resulting jump as a data gap.
            previous_last_id = None
            continue

        gaps = trade_id_gaps(frame)
        if gaps:
            raise TradeDataError(
                f"{symbol} {month:%Y-%m}: {len(gaps)} trade_id gap(s), first at {gaps[0]}"
            )
        duplicates = duplicate_trade_ids(frame)
        if duplicates:
            raise TradeDataError(
                f"{symbol} {month:%Y-%m}: {len(duplicates)} duplicate trade_id(s), "
                f"first {duplicates[0]}"
            )

        # A monthly file whose rows spill into the next month is a silent data-loss
        # path: those rows land in the next month's partition, and writing that month
        # then deletes them (write_parquet uses delete_matching). Observed archives are
        # clean, but the failure mode is invisible, so refuse rather than trust it.
        expected_prefix = month.strftime("%Y-%m")
        stray = sorted(set(frame.loc[~frame["date"].str.startswith(expected_prefix), "date"]))
        if stray:
            raise TradeDataError(
                f"{symbol} {expected_prefix}: archive contains {len(stray)} date(s) outside "
                f"the month ({stray[:3]}); writing the next month would delete them"
            )

        if not frame.empty:
            first_id = int(frame["trade_id"].iloc[0])
            # Continuity *across* months, which per-month checks cannot see: a whole
            # missing file between two intact ones leaves both looking perfect.
            if previous_last_id is not None and first_id != previous_last_id + 1:
                raise TradeDataError(
                    f"{symbol}: trade_id gap across the boundary into {month:%Y-%m}: "
                    f"{previous_last_id} -> {first_id}"
                )
            previous_last_id = int(frame["trade_id"].iloc[-1])

        store(frame, root=root)
        log.info("stored %s %s: %d trades", symbol, month.strftime("%Y-%m"), len(frame))
    return skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download historical Binance USD-M futures trades")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start", required=True, type=dt.date.fromisoformat)
    parser.add_argument("--end", required=True, type=dt.date.fromisoformat)
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="skip months with no archive (e.g. before the symbol was listed)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    skipped = backfill(args.symbol, args.start, args.end, allow_missing=args.allow_missing)
    if skipped:
        log.warning("skipped %d month(s): %s", len(skipped), [m.strftime("%Y-%m") for m in skipped])
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
