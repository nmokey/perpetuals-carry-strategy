"""Historical funding rate downloader (design-doc M1-T2).

This series is the entire input to the M6 persistence model and one of the two terms in
the strategy's edge calculation, so a defect here is a wrong *result*, not a crash.

Two things about the source that are easy to get wrong:

* **Settlement timestamps jitter by ~1 ms** (values end in both ``...0000`` and ``...0001``).
  Differencing in whole hours therefore reports a phantom 7-hour gap between two perfectly
  regular 8-hour settlements. Comparisons here carry an explicit tolerance.
* **The interval is per-symbol *and* varies over time.** Measured: BTC/ETH/DOGE settle every
  8h; ``1000BONKUSDT`` every 4h; ``0GUSDT`` ran 4h at listing and switched to **1h** five
  days later, before returning to 4h by 2026-06. So the cadence is not a symbol constant,
  let alone a global one -- annualisation must read ``funding_interval_hours`` per row.
  Hard-coding 8h would misstate a 1h symbol's annualised funding by 8x.

**Timestamp semantics, for the no-look-ahead invariant.** ``funding_time`` is the moment a
settlement occurred, for the interval that just *ended*. A decision made at time *t* may
use settlements with ``funding_time <= t`` and no others. Treating a settlement as known
one interval early is a textbook look-ahead leak and would inflate every downstream result.
"""

from __future__ import annotations

import argparse
import calendar
import datetime as dt
import logging
from dataclasses import dataclass
from pathlib import Path

import httpx
import pandas as pd

from perpcarry.ingestion import binance_archive as archive
from perpcarry.ingestion.download import DownloadError, cached_fetch, extract_csv, fetch_checksum
from perpcarry.ingestion.fetch_trades import months_between
from perpcarry.storage import data_root, write_parquet

log = logging.getLogger(__name__)

DATASET = "fundingRate"

#: Storage directory under the data root. **Deliberately not** ``DATASET``: that is the
#: *archive's* name for the dataset and appears in URLs, while this is where the
#: normalised rows live. Anything locating funding partitions must use this constant --
#: assuming the two are the same silently finds nothing, which reads as an empty corpus
#: rather than as a wrong path.
STORAGE_DIR = "funding"

#: Output schema per design doc Section 3.3 (plus the ``date`` partition key).
#: Note what is absent: ``mark_price``. The venue does not publish it alongside funding
#: history and it is unused before M7-T4, so it is not emitted -- not even as null.
SCHEMA: dict[str, str] = {
    "funding_time": "int64",
    "symbol": "string",
    "funding_rate": "float64",
    "funding_interval_hours": "int64",
    "date": "string",
}

PARTITION_COLS = ["symbol", "date"]

#: Settlements may drift by a few ms; anything under this is not a gap.
TOLERANCE_MS = 5_000

#: Sanity bound on a single settlement, **not** the venue's published cap -- which cannot
#: be read from here, since `/fapi/v1/fundingInfo` is geo-blocked (B-004). Set far above
#: anything observed (the widest measured was -0.0024 on `0GUSDT`) so it catches corrupt
#: data rather than policy edge cases.
RATE_SANITY_BOUND = 0.05

MS_PER_HOUR = 3_600_000


class FundingDataError(RuntimeError):
    """Downloaded funding data failed a structural check."""


def normalise(raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Map archive columns onto the Section 3.3 schema."""
    missing = {"calc_time", "funding_interval_hours", "last_funding_rate"} - set(raw.columns)
    if missing:
        raise FundingDataError(f"archive schema changed: missing columns {sorted(missing)}")

    funding_time = raw["calc_time"].astype("int64")
    frame = pd.DataFrame(
        {
            "funding_time": funding_time,
            "symbol": pd.array([symbol] * len(raw), dtype="string"),
            "funding_rate": raw["last_funding_rate"].astype("float64"),
            "funding_interval_hours": raw["funding_interval_hours"].astype("int64"),
            "date": pd.to_datetime(funding_time, unit="ms", utc=True)
            .dt.strftime("%Y-%m-%d")
            .astype("string"),
        }
    )
    return frame.sort_values("funding_time", ignore_index=True)


def expected_settlements(month: dt.date, interval_hours: int) -> int:
    """How many settlements a complete month should contain."""
    days = calendar.monthrange(month.year, month.month)[1]
    return days * 24 // interval_hours


def settlement_gaps(
    frame: pd.DataFrame, *, tolerance_ms: int = TOLERANCE_MS
) -> list[tuple[int, int, int]]:
    """Missing settlements, as ``(previous_time, expected_next_time, n_missing)``.

    The tolerance is what stops the source's ~1 ms jitter reading as a gap.

    Each step is measured against the interval on its **later** row, since that is the
    cadence in effect for the period just settled. Doing so handles a mid-window re-cadence
    in either direction with no special case: a 4h→8h switch produces an 8h step whose row
    already says 8h. (An earlier version used the earlier row's interval and needed a skip
    to compensate — a branch no test could distinguish, which is how it was found.)
    """
    if len(frame) < 2:
        return []

    times = frame["funding_time"].to_numpy()
    intervals = frame["funding_interval_hours"].to_numpy()
    gaps: list[tuple[int, int, int]] = []

    for i in range(len(times) - 1):
        expected = int(intervals[i + 1]) * MS_PER_HOUR
        actual = int(times[i + 1]) - int(times[i])
        if actual <= expected + tolerance_ms:
            continue
        missing = round(actual / expected) - 1
        gaps.append((int(times[i]), int(times[i]) + expected, max(missing, 1)))
    return gaps


def interval_changes(frame: pd.DataFrame) -> list[tuple[int, int, int]]:
    """``(funding_time, old_interval, new_interval)`` wherever the cadence changed.

    A venue may re-cadence a symbol mid-window. That is a legitimate event, but it changes
    how funding annualises, so it must surface rather than be smoothed into a gap.
    """
    if len(frame) < 2:
        return []
    intervals = frame["funding_interval_hours"].to_numpy()
    times = frame["funding_time"].to_numpy()
    return [
        (int(times[i + 1]), int(intervals[i]), int(intervals[i + 1]))
        for i in range(len(intervals) - 1)
        if intervals[i] != intervals[i + 1]
    ]


def implausible_rates(frame: pd.DataFrame, *, bound: float = RATE_SANITY_BOUND) -> pd.DataFrame:
    """Rows whose rate is non-finite or beyond the sanity bound."""
    rates = frame["funding_rate"]
    return frame[~rates.between(-bound, bound) | rates.isna()]


def fetch_month(
    symbol: str,
    month: dt.date | str,
    *,
    client: httpx.Client | None = None,
    verify_checksum: bool = True,
) -> pd.DataFrame:
    """Download and normalise one month of funding settlements.

    Monthly is the only granularity published -- there is no ``daily/fundingRate/`` path,
    so the current month is simply absent (404) until it closes rather than served partial.
    """
    url = archive.monthly_url(DATASET, symbol, month)
    digest = fetch_checksum(url, client=client) if verify_checksum else None
    path = cached_fetch(url, expected_sha256=digest, client=client)
    return normalise(extract_csv(path, dtype=str), symbol)


def store(frame: pd.DataFrame, *, root: Path | None = None) -> Path:
    """Write normalised funding to the partitioned Parquet dataset. Idempotent."""
    dest = (root if root is not None else data_root()) / STORAGE_DIR
    return write_parquet(frame, dest, partition_cols=PARTITION_COLS)


@dataclass(frozen=True)
class MonthReport:
    """Facts about a month that are legitimate but must not pass unnoticed."""

    symbol: str
    month: dt.date
    settlements: int
    intervals: tuple[int, ...]
    partial_start: bool
    interval_changes: tuple[tuple[int, int, int], ...]


def month_bounds(month: dt.date) -> tuple[int, int]:
    """``(first_ms, last_ms)`` epoch bounds of the month, in UTC."""
    days = calendar.monthrange(month.year, month.month)[1]
    start = dt.datetime(month.year, month.month, 1, tzinfo=dt.UTC)
    end = start + dt.timedelta(days=days)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def check_month(frame: pd.DataFrame, symbol: str, month: dt.date) -> MonthReport:
    """Raise unless the month is structurally sound; report what is odd but legal.

    Completeness is expressed as **continuity plus endpoint coverage** rather than a raw
    settlement count. The count is only meaningful for a full month at a single cadence,
    and the months where that does not hold are exactly the interesting ones: ``0GUSDT``'s
    listing month runs 4h then switches to 1h partway, so a count check simply skipped
    itself and a month missing half its settlements would have passed.

    A late *start* is legitimate -- a symbol listed mid-month has no earlier settlements --
    so it is reported rather than raised. A short *end* is not: the month has closed, so
    coverage must reach it.
    """
    if frame.empty:
        raise FundingDataError(f"{symbol} {month:%Y-%m}: no settlements")

    prefix = month.strftime("%Y-%m")
    stray = sorted(set(frame.loc[~frame["date"].str.startswith(prefix), "date"]))
    if stray:
        raise FundingDataError(
            f"{symbol} {prefix}: settlements dated outside the month ({stray[:3]})"
        )

    gaps = settlement_gaps(frame)
    if gaps:
        when = dt.datetime.fromtimestamp(gaps[0][1] / 1000, dt.UTC)
        raise FundingDataError(
            f"{symbol} {prefix}: {len(gaps)} gap(s); first missing settlement expected at "
            f"{when:%Y-%m-%d %H:%M} UTC"
        )

    bad = implausible_rates(frame)
    if not bad.empty:
        raise FundingDataError(
            f"{symbol} {prefix}: {len(bad)} implausible rate(s), "
            f"first {bad['funding_rate'].iloc[0]}"
        )

    # Coverage is checked last: a gap gives a far more useful message than a count.
    start_ms, end_ms = month_bounds(month)
    first_ms = int(frame["funding_time"].iloc[0])
    last_ms = int(frame["funding_time"].iloc[-1])
    first_step = int(frame["funding_interval_hours"].iloc[0]) * MS_PER_HOUR
    last_step = int(frame["funding_interval_hours"].iloc[-1]) * MS_PER_HOUR

    # The month has closed, so the final settlement must land within one interval of its
    # end. This catches truncation whatever the interval mix -- which the old count check
    # could not, since it skipped itself whenever the cadence changed.
    if last_ms + last_step < end_ms - TOLERANCE_MS:
        missing_until = dt.datetime.fromtimestamp(end_ms / 1000, dt.UTC)
        raise FundingDataError(
            f"{symbol} {prefix}: coverage ends at "
            f"{dt.datetime.fromtimestamp(last_ms / 1000, dt.UTC):%Y-%m-%d %H:%M} UTC, "
            f"short of the month end ({missing_until:%Y-%m-%d})"
        )

    partial_start = first_ms - first_step > start_ms + TOLERANCE_MS
    intervals = tuple(sorted(set(int(i) for i in frame["funding_interval_hours"])))

    # The design-doc criterion, kept where it is actually meaningful.
    if len(intervals) == 1 and not partial_start:
        expected = expected_settlements(month, intervals[0])
        if len(frame) != expected:
            raise FundingDataError(
                f"{symbol} {prefix}: {len(frame)} settlements, expected {expected}"
            )

    return MonthReport(
        symbol=symbol,
        month=month,
        settlements=len(frame),
        intervals=intervals,
        partial_start=partial_start,
        interval_changes=tuple(interval_changes(frame)),
    )


def backfill(
    symbol: str,
    start: dt.date,
    end: dt.date,
    *,
    root: Path | None = None,
    client: httpx.Client | None = None,
    allow_missing: bool = False,
) -> tuple[list[dt.date], list[MonthReport]]:
    """Fetch and store whole months over ``[start, end]``.

    Returns ``(skipped_months, reports)``. The reports carry the legitimate-but-notable
    facts -- partial listing months and interval changes -- which M1-T4 needs for its
    allowlist and the M9 writeup needs for its caveats. Logging them alone would lose them.
    """
    skipped: list[dt.date] = []
    reports: list[MonthReport] = []
    for month in months_between(start, end):
        try:
            frame = fetch_month(symbol, month, client=client)
        except DownloadError:
            if not allow_missing:
                raise
            log.warning("no %s archive for %s %s -- skipping", DATASET, symbol, month)
            skipped.append(month)
            continue

        report = check_month(frame, symbol, month)
        reports.append(report)
        if report.partial_start:
            log.warning(
                "%s %s: coverage starts mid-month (likely the listing date) -- record it in "
                "the M1-T4 allowlist",
                symbol,
                month.strftime("%Y-%m"),
            )
        for at, old, new in report.interval_changes:
            log.warning(
                "%s: funding interval changed from %dh to %dh at %s -- annualisation "
                "changes with it",
                symbol,
                old,
                new,
                dt.datetime.fromtimestamp(at / 1000, dt.UTC),
            )
        store(frame, root=root)
        log.info("stored %s %s: %d settlements", symbol, month.strftime("%Y-%m"), len(frame))
    return skipped, reports


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download historical funding rates")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start", required=True, type=dt.date.fromisoformat)
    parser.add_argument("--end", required=True, type=dt.date.fromisoformat)
    parser.add_argument("--allow-missing", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    skipped, _ = backfill(args.symbol, args.start, args.end, allow_missing=args.allow_missing)
    if skipped:
        log.warning("skipped %d month(s): %s", len(skipped), [m.strftime("%Y-%m") for m in skipped])
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
