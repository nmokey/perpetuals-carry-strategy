"""UTC archive calendar helpers, independent of any dataset fetcher."""

from __future__ import annotations

import calendar
import datetime as dt
from collections.abc import Iterator


def months_between(start: dt.date, end: dt.date) -> Iterator[dt.date]:
    """First-of-month dates covering ``[start, end]``."""
    cursor = start.replace(day=1)
    while cursor <= end:
        yield cursor
        cursor = (cursor.replace(day=28) + dt.timedelta(days=4)).replace(day=1)


def month_bounds(month: dt.date) -> tuple[int, int]:
    """``(first_ms, last_ms)`` epoch bounds of the month, in UTC."""
    days = calendar.monthrange(month.year, month.month)[1]
    start = dt.datetime(month.year, month.month, 1, tzinfo=dt.UTC)
    end = start + dt.timedelta(days=days)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)
