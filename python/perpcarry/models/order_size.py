"""Order size in comparable units — %ADV and %depth (M4-T3).

"Buy 50,000 0G" is not comparable to "buy 50,000 BTC"; "buy 1% of ADV" is. M8's cross-symbol
comparison is impossible without this, and M5's calibration is far less useful in raw units — a
fit in base units describes one symbol in one liquidity regime.

**Two normalizations, because they answer different questions.** %ADV is the standard axis in the
impact literature and the one M8 compares across symbols. %depth is what predicts *this* order's
cost, because it is the liquidity actually present at that instant. They diverge exactly where it
matters — on a thin book during a volume spike — and M5 fits against both and reports which explains
more. That comparison is itself a finding worth having.

**The look-ahead trap, which is the natural way to write this.** ADV must be computed from a window
ending strictly *before* the instant it normalizes. An ADV over the whole sample, used to size an
order on day 3, is leakage of exactly the kind ranked first among things that invalidate this work.
:func:`average_daily_volume` therefore takes an ``as_of`` and excludes it, and there is a test for
that rather than a comment about it.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

import pandas as pd

from perpcarry.ingestion import derive_symbol_meta, fetch_trades
from perpcarry.storage import data_root

#: Default trailing window. Explicit and rolling by design: a fixed calendar month would make an
#: order's %ADV jump discontinuously at month boundaries for no market reason.
DEFAULT_ADV_DAYS = 30


class OrderSizeError(ValueError):
    """A size could not be normalized, or the inputs to do so were unusable."""


def daily_volumes(
    symbol: str,
    *,
    root: Path | None = None,
    start: dt.date | None = None,
    end: dt.date | None = None,
) -> pd.Series:
    """Base-asset volume traded per UTC day, indexed by ISO date.

    Summed from the ``trades`` corpus rather than from klines, because that is the dataset M5 and
    M7 consume: calibrating against one source and executing against another is how a study ends up
    internally inconsistent (D-022).
    """
    base = data_root() if root is None else Path(root)
    directory = base / fetch_trades.STORAGE_DIR / f"symbol={symbol}"
    if not directory.is_dir():
        raise OrderSizeError(f"no trades partitions for {symbol} at {directory}")

    rows: dict[str, float] = {}
    for partition in sorted(directory.glob("date=*")):
        day = partition.name.removeprefix("date=")
        if start is not None and day < start.isoformat():
            continue
        if end is not None and day > end.isoformat():
            continue
        total = 0.0
        for path in sorted(partition.glob("*.parquet")):
            total += float(pd.read_parquet(path, columns=["quantity"])["quantity"].sum())
        rows[day] = total

    if not rows:
        raise OrderSizeError(f"no trades partitions for {symbol} in the requested range")
    return pd.Series(rows, name="volume").sort_index()


def average_daily_volume(
    symbol: str,
    as_of: dt.date | str,
    *,
    days: int = DEFAULT_ADV_DAYS,
    root: Path | None = None,
) -> float:
    """Mean daily base volume over the ``days`` UTC days *before* ``as_of``.

    ``as_of`` is excluded. A decision made during a day may not use that day's completed volume,
    which is not knowable until the day ends.
    """
    if days < 1:
        raise OrderSizeError(f"ADV window must be at least one day, got {days}")
    day = dt.date.fromisoformat(as_of) if isinstance(as_of, str) else as_of

    volumes = daily_volumes(
        symbol, root=root, start=day - dt.timedelta(days=days), end=day - dt.timedelta(days=1)
    )
    if volumes.empty:
        raise OrderSizeError(f"{symbol}: no trades in the {days} days before {day}")
    return float(volumes.mean())


def as_fraction_of_adv(
    quantity: float,
    symbol: str,
    as_of: dt.date | str,
    *,
    days: int = DEFAULT_ADV_DAYS,
    root: Path | None = None,
) -> float:
    """``quantity`` as a fraction of ADV. 0.01 means 1% of average daily volume."""
    adv = average_daily_volume(symbol, as_of, days=days, root=root)
    if not adv > 0:
        raise OrderSizeError(f"{symbol}: ADV is {adv}, cannot express a size as a fraction of it")
    return quantity / adv


def quantity_from_adv_fraction(
    fraction: float,
    symbol: str,
    as_of: dt.date | str,
    *,
    days: int = DEFAULT_ADV_DAYS,
    root: Path | None = None,
) -> float:
    """The inverse of :func:`as_fraction_of_adv`, for sweeping sizes in comparable units."""
    return fraction * average_daily_volume(symbol, as_of, days=days, root=root)


def visible_depth(levels: Sequence[tuple[float, float]], depth: int) -> tuple[float, int]:
    """``(summed quantity over the top `depth` levels, levels actually present)``.

    The level count comes back alongside deliberately. A book thinner than ``depth`` would
    otherwise inflate every fraction computed against it — a smaller denominator reads as a
    *larger* order, and nothing in the number itself says the book was thin.
    """
    if depth < 1:
        raise OrderSizeError(f"depth must be at least one level, got {depth}")
    used = list(levels)[:depth]
    return float(sum(quantity for _, quantity in used)), len(used)


def as_fraction_of_depth(
    quantity: float, levels: Sequence[tuple[float, float]], *, depth: int = 25
) -> tuple[float, int]:
    """``quantity`` as a fraction of visible top-``depth`` liquidity, with the level count.

    ``levels`` is the side the order would *consume* — the asks for a buy. Passing the wrong side
    yields a plausible number computed against liquidity the order would never touch, which is why
    the caller names it rather than this function guessing from a side flag.
    """
    total, present = visible_depth(levels, depth)
    if not total > 0:
        raise OrderSizeError("no visible liquidity on that side; cannot express a size against it")
    return quantity / total, present


def round_to_step(quantity: float, symbol: str) -> float:
    """Round down to the symbol's ``step_size``, read from the committed lookup table.

    Committed data, never recomputed at runtime: a step size that silently changed between runs
    would make backtests irreproducible. Rounds *down* so a normalized size never becomes an order
    larger than the one that was asked for.
    """
    table = derive_symbol_meta.load_table()
    if symbol not in table:
        raise OrderSizeError(f"{symbol} is not in symbol_meta.json; add it before sizing orders")

    # `step_size` is already a Decimal on the committed record. Taken as-is rather than routed
    # through str(): the table exists precisely so this value is exact and stable, and
    # re-parsing it here would be a second chance to get it wrong.
    step = table[symbol].step_size
    if step <= 0:
        raise OrderSizeError(f"{symbol}: step_size is {step}")
    return float((Decimal(str(quantity)) // step) * step)
