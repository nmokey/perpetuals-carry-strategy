"""Symbol tick/step size derivation (design-doc M1-T5).

The metadata has no obtainable authoritative source: ``exchangeInfo`` is geo-blocked, the
S3 archive carries no metadata tree, and the vendor's instruments API is paid-only. So we
infer it -- tick size is the GCD of observed prices, step size the GCD of observed
quantities (blocker B-007).

Two things in here are load-bearing and easy to break silently.

**Decimal, never float.** A GCD over binary floats is nonsense: ``0.3`` is not three
tenths. Every value is carried as :class:`~decimal.Decimal` from the CSV text, and
:func:`decimal_gcd` *rejects* ``float`` inputs rather than converting them, because a
silent conversion is exactly the bug that would not surface in any output.

**Scale by the maximum decimal exponent, not the minimum.** The first probe of this
technique used ``min`` and reported ``0.0001`` as ``0.01`` -- a 100x error that looked
entirely plausible, produced no exception, and would have made the book appear coarser
than it is while quietly biasing every impact estimate.

What this recovers is *observed* granularity, which equals the true tick only when enough
distinct values occurred. It can overestimate on a thin window (if no two trades ever
landed one tick apart, the GCD is a multiple of the truth); it can never underestimate.
Hence :data:`MIN_DISTINCT_VALUES` and the ``confident`` flag: the failure mode is a
plausible wrong number rather than an error, so the code has to be able to say "not
enough data".
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import reduce
from pathlib import Path

import httpx
import pandas as pd

from perpcarry.ingestion import binance_archive as archive
from perpcarry.ingestion.download import cached_fetch, extract_csv, fetch_checksum

log = logging.getLogger(__name__)

DATASET = "trades"

#: Committed lookup table. Reviewable in diffs and stable across runs -- a value that
#: silently changed between runs would make backtests irreproducible.
TABLE_PATH = Path(__file__).parent / "symbol_meta.json"

#: Below this many distinct observed values the estimate is reported as low-confidence.
#:
#: For the GCD to overestimate by a factor ``k``, every one of the ``n`` distinct scaled
#: values must be divisible by ``k``. Treating the values as arbitrary multiples of the
#: true tick, that runs at roughly ``k**-(n-1)``, so at n=20 even a factor of 2 surviving
#: is about a one-in-500,000 coincidence. The thinnest window verified against real data
#: (0GUSDT, 2026-08-01) had 81 distinct prices and agreed with two much richer windows.
MIN_DISTINCT_VALUES = 20


class SymbolMetaError(RuntimeError):
    """Derivation could not produce a trustworthy value."""


def _to_decimal(value: Decimal | str | int) -> Decimal:
    """Convert to ``Decimal`` exactly, refusing floats.

    Rejecting rather than converting is deliberate. ``Decimal(0.1)`` is
    ``0.1000000000000000055511151231257827...``, and a GCD over values like that returns
    a number with no relationship to the tick -- but still *a* number, which would be
    committed to the table and believed.
    """
    if isinstance(value, float):
        raise TypeError(
            "float values are rejected: a GCD over binary floats is meaningless. "
            "Pass Decimal or the original decimal string."
        )
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, str)):
        try:
            return Decimal(value)
        except InvalidOperation as exc:
            raise SymbolMetaError(f"not a decimal value: {value!r}") from exc
    raise TypeError(f"cannot derive a grid from {type(value).__name__}")


def _decimal_places(value: Decimal) -> int:
    """Digits after the point, or 0 for an integral value."""
    exponent = value.as_tuple().exponent
    # Only ever an int for finite values; NaN/Inf carry a string exponent.
    if not isinstance(exponent, int):
        raise SymbolMetaError(f"non-finite value: {value}")
    return max(-exponent, 0)


def _as_scaled_int(value: Decimal, places: int) -> int:
    """``value * 10**places`` as an exact integer.

    Done on the digit tuple rather than via ``scaleb`` so the active decimal context's
    precision cannot round a long price on the way through.
    """
    _, digits, exponent = value.as_tuple()
    unscaled = int("".join(str(d) for d in digits))
    shift = exponent + places
    if shift < 0:  # pragma: no cover - places is the max, so this cannot happen
        raise SymbolMetaError(f"scaling {value} by {places} places would truncate it")
    return unscaled * 10**shift


def decimal_gcd(values: Iterable[Decimal | str | int]) -> Decimal:
    """Greatest common divisor of positive decimal values, computed exactly.

    Scales every value to an integer by the **maximum** number of decimal places present
    -- using the minimum instead truncates the finer values to zero and reports a grid
    that is too coarse by a power of ten.
    """
    decimals = [_to_decimal(v) for v in values]
    if not decimals:
        raise SymbolMetaError("cannot derive a grid from no values")

    non_positive = [d for d in decimals if d <= 0]
    if non_positive:
        raise SymbolMetaError(
            f"non-positive value(s) in the sample, first {non_positive[0]}: "
            "a zero price or quantity is a data defect, not a grid point"
        )

    places = max(_decimal_places(d) for d in decimals)
    scaled = (_as_scaled_int(d, places) for d in decimals)
    common = reduce(math.gcd, scaled)
    # ``normalize`` strips trailing zeros the source text carried -- quantities arrive as
    # "1.0", "10.0", so the raw result is 1.0 where the grid is 1. Numerically identical,
    # but this table is committed and read by humans. ``format(..., "f")`` then forces
    # plain notation, since normalize renders 100 as 1E+2 and 0.0001 must not become 1E-4.
    return Decimal(format(Decimal(common).scaleb(-places).normalize(), "f"))


@dataclass(frozen=True)
class GridEstimate:
    """A derived tick or step size, with the evidence behind it.

    Carries the distinct observations themselves, not just how many there were, so that
    windows can be pooled by **union**. Counting evidence any other way overstates it:
    the same price seen on three days is one distinct value, not three, and
    :data:`MIN_DISTINCT_VALUES` rests on a probability argument over distinct values.
    """

    value: Decimal
    values: frozenset[Decimal]
    samples: int

    @property
    def distinct(self) -> int:
        return len(self.values)

    @property
    def confident(self) -> bool:
        return self.distinct >= MIN_DISTINCT_VALUES

    @property
    def caveat(self) -> str | None:
        if self.confident:
            return None
        return (
            f"only {self.distinct} distinct value(s) in {self.samples} sample(s) "
            f"(want >= {MIN_DISTINCT_VALUES}): {self.value} may be a multiple of the "
            "true grid. Widen the window."
        )


def estimate_grid(values: Sequence[Decimal | str | int]) -> GridEstimate:
    """Derive a grid from observed values, recording the evidence that supported it."""
    # Dedup on the incoming representation first: a full ETHUSDT day is 12M rows against
    # ~17k distinct prices, and converting every row to Decimal before deduping costs a
    # gigabyte for nothing.
    seen = dict.fromkeys(values)
    # Then dedup again on *numeric* value, because the first pass compares text: an
    # archive writing both "1.0" and "1.00" would otherwise count one grid point twice.
    unique = frozenset(_to_decimal(v) for v in seen)
    return GridEstimate(value=decimal_gcd(unique), values=unique, samples=len(values))


@dataclass(frozen=True)
class WindowEstimate:
    """One day's worth of evidence for one symbol."""

    symbol: str
    date: str
    tick: GridEstimate
    step: GridEstimate


@dataclass(frozen=True)
class SymbolMeta:
    """The committed record for one symbol."""

    symbol: str
    tick_size: Decimal
    step_size: Decimal
    windows: tuple[str, ...]
    trades: int
    distinct_prices: int
    distinct_quantities: int
    derived_on: str
    confident: bool
    caveats: tuple[str, ...] = ()

    def to_json(self) -> dict:
        """Serialise with the sizes as *strings*.

        JSON has one number type and it is a float. Writing ``0.0001`` as a JSON number
        would put the value back through binary floating point on every read -- undoing
        the entire reason this module refuses floats.
        """
        return {
            "symbol": self.symbol,
            "tick_size": format(self.tick_size, "f"),
            "step_size": format(self.step_size, "f"),
            "windows": list(self.windows),
            "trades": self.trades,
            "distinct_prices": self.distinct_prices,
            "distinct_quantities": self.distinct_quantities,
            "derived_on": self.derived_on,
            "confident": self.confident,
            "caveats": list(self.caveats),
        }

    @classmethod
    def from_json(cls, payload: dict) -> SymbolMeta:
        for field in ("tick_size", "step_size"):
            if not isinstance(payload[field], str):
                raise SymbolMetaError(
                    f"{payload.get('symbol', '?')}.{field} is "
                    f"{type(payload[field]).__name__}, expected a string -- a JSON number "
                    "here means the value has already been through a float"
                )
        return cls(
            symbol=payload["symbol"],
            tick_size=Decimal(payload["tick_size"]),
            step_size=Decimal(payload["step_size"]),
            windows=tuple(payload["windows"]),
            trades=payload["trades"],
            distinct_prices=payload["distinct_prices"],
            distinct_quantities=payload["distinct_quantities"],
            derived_on=payload["derived_on"],
            confident=payload["confident"],
            caveats=tuple(payload.get("caveats", ())),
        )


def estimate_window(raw: pd.DataFrame, symbol: str, date: dt.date | str) -> WindowEstimate:
    """Derive tick and step from one raw trades CSV.

    Takes the *raw* archive frame, read with ``dtype=str``, not the normalised frame from
    :mod:`perpcarry.ingestion.fetch_trades` -- normalisation casts price and quantity to
    ``float64``, and this module cannot accept floats.
    """
    missing = {"price", "qty"} - set(raw.columns)
    if missing:
        raise SymbolMetaError(f"archive schema changed: missing columns {sorted(missing)}")
    if raw.empty:
        raise SymbolMetaError(f"{symbol} {date}: no trades in the window")

    # Check the *element* type, not the column dtype: pandas 3 reads dtype=str columns as
    # StringDtype while pandas 2 used object, and neither name is the property that
    # matters. What matters is that the value is still decimal text.
    for column in ("price", "qty"):
        sample = raw[column].iloc[0]
        if not isinstance(sample, str):
            raise SymbolMetaError(
                f"{column} arrived as {type(sample).__name__}, not text -- read the "
                "archive CSV with dtype=str so the decimal digits survive"
            )

    day = date.isoformat() if isinstance(date, dt.date) else str(date)
    return WindowEstimate(
        symbol=symbol,
        date=day,
        tick=estimate_grid(list(raw["price"])),
        step=estimate_grid(list(raw["qty"])),
    )


def raw_day(
    symbol: str,
    date: dt.date | str,
    *,
    client: httpx.Client | None = None,
    verify_checksum: bool = True,
) -> pd.DataFrame:
    """Download one day of trades as raw decimal text."""
    url = archive.daily_url(DATASET, symbol, date)
    digest = fetch_checksum(url, client=client) if verify_checksum else None
    path = cached_fetch(url, expected_sha256=digest, client=client)
    return extract_csv(path, dtype=str)


def combine(
    estimates: Sequence[WindowEstimate], *, derived_on: dt.date | None = None
) -> SymbolMeta:
    """Fold per-window estimates into one committed record.

    Disagreement across disjoint windows is an **error**, not something to resolve by
    taking the finest value. Two different causes produce it -- a window too thin to
    resolve the grid, or the venue genuinely re-ticking the symbol mid-study -- and they
    call for opposite responses. Widening the window distinguishes them; silently picking
    the finest hides a re-tick inside the study period.
    """
    if not estimates:
        raise SymbolMetaError("no windows to combine")

    symbols = {e.symbol for e in estimates}
    if len(symbols) > 1:
        raise SymbolMetaError(f"cannot combine windows from different symbols: {sorted(symbols)}")

    for field in ("tick", "step"):
        values = {getattr(e, field).value for e in estimates}
        if len(values) > 1:
            detail = ", ".join(f"{e.date}={getattr(e, field).value}" for e in estimates)
            raise SymbolMetaError(
                f"{estimates[0].symbol}: {field} size disagrees across windows ({detail}). "
                "Widen the window rather than picking the finest -- a disagreement may "
                "equally mean the venue re-ticked the symbol."
            )

    symbol = estimates[0].symbol
    trades = sum(e.tick.samples for e in estimates)

    # Pool by union, not by sum. Summing per-window counts would count a price seen on
    # all three days as three pieces of evidence, inflating confidence exactly where the
    # windows overlap most -- which is the case where they are least independent.
    pooled = {
        field: GridEstimate(
            value=decimal_gcd(
                union := frozenset().union(*(getattr(e, field).values for e in estimates))
            ),
            values=union,
            samples=trades,
        )
        for field in ("tick", "step")
    }
    tick, step = pooled["tick"], pooled["step"]

    caveats: list[str] = []
    # Confidence is judged on the pooled evidence, not per window: three thin days that
    # observe *different* prices are better evidence than any one of them alone.
    if not tick.confident:
        caveats.append(f"tick size: {tick.caveat}")
    if not step.confident:
        caveats.append(f"step size: {step.caveat}")
    if len(estimates) < 2:
        caveats.append(
            "derived from a single window: stability across disjoint windows is the "
            "acceptance criterion and was not checked"
        )

    return SymbolMeta(
        symbol=symbol,
        tick_size=tick.value,
        step_size=step.value,
        windows=tuple(e.date for e in estimates),
        trades=trades,
        distinct_prices=tick.distinct,
        distinct_quantities=step.distinct,
        derived_on=(derived_on or dt.date.today()).isoformat(),
        confident=not caveats,
        caveats=tuple(caveats),
    )


def derive(
    symbol: str,
    dates: Sequence[dt.date | str],
    *,
    client: httpx.Client | None = None,
    derived_on: dt.date | None = None,
) -> SymbolMeta:
    """Download each window and fold the results into one record."""
    estimates = []
    for date in dates:
        raw = raw_day(symbol, date, client=client)
        estimate = estimate_window(raw, symbol, date)
        log.info(
            "%s %s: tick=%s step=%s (%d trades, %d distinct prices)",
            symbol,
            estimate.date,
            estimate.tick.value,
            estimate.step.value,
            estimate.tick.samples,
            estimate.tick.distinct,
        )
        estimates.append(estimate)
    return combine(estimates, derived_on=derived_on)


def sample_days(start: dt.date, end: dt.date, *, day: int = 1) -> list[dt.date]:
    """First, middle and last month of ``[start, end]``, one day each.

    Disjoint windows spanning the study period, per the spec's Q1: they cost far less than
    a contiguous month and are a strictly better check, because separation in *time* is
    what detects a mid-study re-tick.
    """
    if end < start:
        raise SymbolMetaError(f"end {end} precedes start {start}")
    first = start.replace(day=day)
    last = end.replace(day=day)
    # Month indices are zero-based here; using 1-based month numbers puts the midpoint a
    # month late and, on a single-month range, invents a second window after the end.
    first_index = first.year * 12 + first.month - 1
    last_index = last.year * 12 + last.month - 1
    middle_index = (first_index + last_index) // 2
    middle = dt.date(middle_index // 12, middle_index % 12 + 1, day)
    return sorted({first, middle, last})


def load_table(path: Path | None = None) -> dict[str, SymbolMeta]:
    """Read the committed lookup table."""
    table_path = path if path is not None else TABLE_PATH
    if not table_path.exists():
        return {}
    payload = json.loads(table_path.read_text())
    return {name: SymbolMeta.from_json(entry) for name, entry in payload.items()}


def save_table(table: dict[str, SymbolMeta], path: Path | None = None) -> Path:
    """Write the lookup table, sorted so diffs stay reviewable."""
    table_path = path if path is not None else TABLE_PATH
    payload = {name: table[name].to_json() for name in sorted(table)}
    table_path.write_text(json.dumps(payload, indent=2) + "\n")
    return table_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Derive Binance USD-M symbol tick/step sizes")
    parser.add_argument("--symbol", required=True)
    parser.add_argument(
        "--date",
        action="append",
        type=dt.date.fromisoformat,
        help="a window to sample; repeat for each. Defaults to --start/--end sampling.",
    )
    parser.add_argument("--start", type=dt.date.fromisoformat)
    parser.add_argument("--end", type=dt.date.fromisoformat)
    parser.add_argument(
        "--write",
        action="store_true",
        help=f"merge the result into {TABLE_PATH.name} instead of only printing it",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    dates = args.date
    if not dates:
        if not (args.start and args.end):
            parser.error("pass --date (repeatable) or both --start and --end")
        dates = sample_days(args.start, args.end)

    meta = derive(args.symbol, dates)
    print(json.dumps(meta.to_json(), indent=2))

    for caveat in meta.caveats:
        log.warning("%s: %s", meta.symbol, caveat)

    if args.write:
        if not meta.confident:
            log.error("refusing to commit a low-confidence estimate for %s", meta.symbol)
            return 1
        table = load_table()
        table[meta.symbol] = meta
        save_table(table)
        log.info("wrote %s", TABLE_PATH)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
