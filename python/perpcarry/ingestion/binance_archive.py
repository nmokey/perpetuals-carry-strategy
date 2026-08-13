"""URL construction for the Binance USD-M futures public archive.

Kept separate from the fetchers because every M1 task needs it and the path shapes are
not uniform -- `klines` nests under an interval directory, `fundingRate` exists only
monthly, `bookDepth` only daily. Getting one of those wrong yields a 404, which is at
least loud; reusing the flat builder for `klines` yields a 404 that looks like missing
data, which is not.
"""

from __future__ import annotations

import datetime as dt

BASE = "https://data.binance.vision/data/futures/um"


def _date_str(date: dt.date | str) -> str:
    return date.isoformat() if isinstance(date, dt.date) else date


def _month_str(month: dt.date | str) -> str:
    return month.strftime("%Y-%m") if isinstance(month, dt.date) else month


def daily_url(dataset: str, symbol: str, date: dt.date | str) -> str:
    """Daily archive URL, e.g. ``daily/trades/BTCUSDT/BTCUSDT-trades-2026-08-01.zip``."""
    day = _date_str(date)
    return f"{BASE}/daily/{dataset}/{symbol}/{symbol}-{dataset}-{day}.zip"


def monthly_url(dataset: str, symbol: str, month: dt.date | str) -> str:
    """Monthly archive URL, e.g. ``monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2026-06.zip``."""
    ym = _month_str(month)
    return f"{BASE}/monthly/{dataset}/{symbol}/{symbol}-{dataset}-{ym}.zip"


def klines_daily_url(symbol: str, date: dt.date | str, interval: str = "1m") -> str:
    """Klines are the exception: an extra ``{interval}/`` path segment.

    Reusing :func:`daily_url` for klines produces a 404 that reads as missing data.
    """
    day = _date_str(date)
    return f"{BASE}/daily/klines/{symbol}/{interval}/{symbol}-{interval}-{day}.zip"


def klines_monthly_url(symbol: str, month: dt.date | str, interval: str = "1m") -> str:
    ym = _month_str(month)
    return f"{BASE}/monthly/klines/{symbol}/{interval}/{symbol}-{interval}-{ym}.zip"


# Column names for the klines CSV, which ships without a header row.
KLINE_COLUMNS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "count",
    "taker_buy_volume",
    "taker_buy_quote_volume",
    "ignore",
]
