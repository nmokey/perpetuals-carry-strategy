"""URL construction for the Tardis.dev free-tier datasets (design-doc M1-T3, OD-2).

Kept separate from :mod:`perpcarry.ingestion.fetch_book` for the same reason
:mod:`perpcarry.ingestion.binance_archive` is separate from the Binance fetchers: the
path shape is a fact about the vendor, and more than one task needs it -- M1-T3 pulls
``incremental_book_L2``, M2-T2 validates against ``book_snapshot_25``.

**The free tier serves the first day of every month and nothing else.** Verified
2026-08-12 by probe: day 1 returns HTTP 200 back to at least 2020-01-01, every other day
returns 401. A naive date loop 401s on the 2nd, which reads like an auth problem rather
than the tier limit it actually is -- hence :func:`require_free_tier_day`, which refuses
before the request is made.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

BASE = "https://datasets.tardis.dev/v1"
EXCHANGE = "binance-futures"

#: Snapshot + diffs; the primary dataset for book reconstruction (§3.2).
INCREMENTAL_BOOK_L2 = "incremental_book_L2"
#: Independent top-25 reference, used to validate replay in M2-T2.
BOOK_SNAPSHOT_25 = "book_snapshot_25"

DATASETS = (INCREMENTAL_BOOK_L2, BOOK_SNAPSHOT_25)


class FreeTierError(ValueError):
    """A requested day is outside what the free tier serves."""


def is_free_tier_day(date: dt.date) -> bool:
    """The free tier serves only the first of each month."""
    return date.day == 1


def require_free_tier_day(date: dt.date) -> None:
    """Raise unless ``date`` is one the free tier will serve.

    Checked before the request so the failure names the tier limit. The server's own
    answer is a bare 401, which is indistinguishable from a credentials problem and sends
    the reader looking for an API key that this project deliberately does not use.
    """
    if not is_free_tier_day(date):
        raise FreeTierError(
            f"{date.isoformat()} is not available on the Tardis free tier, which serves "
            f"only the first day of each month -- use {date.replace(day=1).isoformat()}. "
            "This is a tier limitation, not an authentication failure (OD-2, M1-T3)."
        )


def dataset_url(dataset: str, symbol: str, date: dt.date, *, exchange: str = EXCHANGE) -> str:
    """Free-tier dataset URL for one symbol-day.

    e.g. ``.../v1/binance-futures/incremental_book_L2/2026/06/01/0GUSDT.csv.gz``
    """
    if dataset not in DATASETS:
        raise ValueError(f"unknown dataset {dataset!r}, expected one of {list(DATASETS)}")
    require_free_tier_day(date)
    return f"{BASE}/{exchange}/{dataset}/{date:%Y/%m/%d}/{symbol}.csv.gz"


def free_tier_days(start: dt.date, end: dt.date) -> Iterator[dt.date]:
    """First-of-month days within ``[start, end]``, inclusive.

    Use this rather than a day-by-day loop -- see the module docstring.
    """
    if end < start:
        raise ValueError(f"end {end} precedes start {start}")
    cursor = start.replace(day=1)
    if cursor < start:
        cursor = (cursor.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    while cursor <= end:
        yield cursor
        cursor = (cursor.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
