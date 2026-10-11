"""Validated, evidence-bound funding series for statistical research; no downloads."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from perpcarry.ingestion import fetch_funding
from perpcarry.integrity import partition_fingerprint


class FundingSeriesError(ValueError):
    """A requested funding window is incomplete, inconsistent or changed."""


def utc_ms(day: dt.date) -> int:
    return int(dt.datetime.combine(day, dt.time(), tzinfo=dt.UTC).timestamp() * 1000)


def validate(frame: pd.DataFrame, start: dt.date, end: dt.date) -> None:
    """Check one symbol over [start, end), retaining original settlement timestamps.

    Cadence changes are legal, but spacing must follow the later row's declared interval.
    Endpoint coverage is strict; listing/partial windows require a different explicit scope.
    """
    if start >= end or frame.empty or not set(fetch_funding.SCHEMA) <= set(frame.columns):
        raise FundingSeriesError("empty or incomplete funding window/schema")
    if frame.isna().any().any() or frame.symbol.nunique() != 1:
        raise FundingSeriesError("null values or mixed symbols")
    for key in ("funding_time", "funding_interval_hours"):
        if not pd.api.types.is_integer_dtype(frame[key].dtype):
            raise FundingSeriesError(f"{key} must have integer dtype")
    times = frame.funding_time.to_numpy(dtype=np.int64)
    hours = frame.funding_interval_hours.to_numpy(dtype=np.int64)
    rates = frame.funding_rate.to_numpy(dtype=float)
    if not np.isfinite(rates).all() or (np.abs(rates) > fetch_funding.RATE_SANITY_BOUND).any():
        raise FundingSeriesError("nonfinite or implausible funding rate")
    if ((hours <= 0) | (hours > 24)).any():
        raise FundingSeriesError("invalid funding cadence")
    dates = pd.to_datetime(times, unit="ms", utc=True).strftime("%Y-%m-%d")
    if not np.array_equal(frame.date.to_numpy(), dates.to_numpy()):
        raise FundingSeriesError("funding timestamp/date mismatch")
    first, stop = utc_ms(start), utc_ms(end)
    if (times < first).any() or (times >= stop).any():
        raise FundingSeriesError("settlement outside requested UTC window")
    steps = np.diff(times)
    if (steps <= 0).any():
        raise FundingSeriesError("duplicate or unordered funding settlements")
    expected_steps = hours[1:] * fetch_funding.MS_PER_HOUR
    if (np.abs(steps - expected_steps) > fetch_funding.TOLERANCE_MS).any():
        raise FundingSeriesError("missing or irregular funding settlements")
    if (
        times[0] - first > fetch_funding.TOLERANCE_MS
        or abs(stop - times[-1] - hours[-1] * fetch_funding.MS_PER_HOUR)
        > fetch_funding.TOLERANCE_MS
    ):
        raise FundingSeriesError("funding window lacks endpoint coverage")
    expected_days = {(start + dt.timedelta(days=i)).isoformat() for i in range((end - start).days)}
    if set(frame.date) != expected_days:
        raise FundingSeriesError("missing UTC funding days")


def load(
    root: Path,
    symbol: str,
    start: dt.date,
    end: dt.date,
    *,
    expected_hashes: dict[str, str] | None = None,
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Read only requested partitions, checking structural coverage and read stability.

    Optional prior evidence must cover every selected fragment and match its content.
    Fragments are read explicitly so report sidecars/Hive schema inference cannot interfere.
    """
    root = Path(root)
    frames, evidence = [], {}
    for offset in range((end - start).days):
        day = start + dt.timedelta(days=offset)
        directory = root / fetch_funding.STORAGE_DIR / f"symbol={symbol}" / f"date={day}"
        before = partition_fingerprint(directory)
        if not before:
            raise FundingSeriesError(f"missing funding partition: {symbol} {day}")
        for name, digest in before.items():
            path = directory / name
            relative = str(path.relative_to(root))
            if expected_hashes is not None and expected_hashes.get(relative) != digest:
                raise FundingSeriesError(f"missing or stale funding evidence: {relative}")
            frame = pq.ParquetFile(path).read().to_pandas()
            for key, value in (("symbol", symbol), ("date", day.isoformat())):
                if key in frame and not (frame[key] == value).all():
                    raise FundingSeriesError(f"partition identity mismatch: {relative}")
                frame[key] = value
            frames.append(frame)
            evidence[relative] = digest
        if partition_fingerprint(directory) != before:
            raise FundingSeriesError(f"funding changed while loading: {symbol} {day}")
    if not frames:
        raise FundingSeriesError("no funding partitions in requested window")
    result = pd.concat(frames, ignore_index=True)
    validate(result, start, end)
    # Recheck the entire selection so a previously read day cannot change unnoticed.
    current = {
        str((directory / name).relative_to(root)): digest
        for offset in range((end - start).days)
        for directory in [
            root
            / fetch_funding.STORAGE_DIR
            / f"symbol={symbol}"
            / f"date={start + dt.timedelta(days=offset)}"
        ]
        for name, digest in partition_fingerprint(directory).items()
    }
    if current != evidence:
        raise FundingSeriesError("funding selection changed while loading")
    return result, evidence
