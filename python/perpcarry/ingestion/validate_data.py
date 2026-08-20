"""Corpus-level data validation (design-doc M1-T4).

The per-fetcher tests in M1-T1/T2/T3 validate *a download*. This validates *the corpus*:
coverage, cross-dataset consistency, and defects only visible in aggregate. It matters
because data defects are the class of bug that produces plausible-looking wrong numbers
rather than a crash, which is the worst kind for a project whose deliverable is a number.

**A validator that cannot be shown to fail on known-bad input is worse than no validator**
-- it converts "we didn't check" into "we checked and it was fine". Every check here has a
test that corrupts a clean fixture in exactly one way and asserts that this check, and
only this check, fires (convention C12).

**"Unexplained" is doing real work in the acceptance criterion.** Some gaps are legitimate:
venue downtime, a symbol's listing date, the upstream hole already found in
``1000BONKUSDT`` funding. Those are acknowledged in ``data_quality_allowlist.toml`` with a
reason and a date; anything nobody has looked at fails. Without that distinction the
criterion is either unachievable or gets satisfied by weakening the checks.

Two checks need the network and are therefore **opt-in**, defaulting to skipped rather
than silently passing: archive checksum re-verification and the exact volume
reconciliation against ``klines`` (which is not stored in the corpus). A skipped check is
reported as skipped -- never as a pass.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import tomllib
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from perpcarry.ingestion import fetch_book, fetch_funding, fetch_trades
from perpcarry.ingestion import tardis_archive as tardis
from perpcarry.storage import data_root, read_parquet

log = logging.getLogger(__name__)

ALLOWLIST_PATH = Path(__file__).parent / "data_quality_allowlist.toml"

# Storage directory names, taken from the fetchers themselves. Hard-coding these -- or
# reaching for the fetchers' archive-facing DATASET constants -- makes the validator look
# in the wrong place and report an empty corpus instead of a wrong path.
TRADES = fetch_trades.STORAGE_DIR
FUNDING = fetch_funding.STORAGE_DIR
BOOK = fetch_book.DATASET_DIRS[tardis.INCREMENTAL_BOOK_L2]
BOOK_SNAPSHOT = fetch_book.DATASET_DIRS[tardis.BOOK_SNAPSHOT_25]

#: Directory name under the data root for each dataset.
DATASET_DIRS = {TRADES: TRADES, FUNDING: FUNDING, BOOK: BOOK, BOOK_SNAPSHOT: BOOK_SNAPSHOT}

#: The one venue the whole project uses (D-009). A mixed-venue corpus is fatal to the
#: result, not merely untidy -- funding and book would describe different markets.
EXPECTED_VENUE = tardis.EXCHANGE


class ValidationError(RuntimeError):
    """The validator could not run -- distinct from the data failing a check."""


@dataclass(frozen=True)
class CheckResult:
    """One check's verdict for one scope.

    ``date`` is ``None`` for checks whose scope is a whole symbol or the whole corpus.
    """

    check: str
    dataset: str
    symbol: str | None
    date: str | None
    passed: bool
    detail: str
    skipped: bool = False
    allowlisted: bool = False

    @property
    def counts_as_failure(self) -> bool:
        return not self.passed and not self.skipped and not self.allowlisted

    def to_json(self) -> dict:
        return {
            "check": self.check,
            "dataset": self.dataset,
            "symbol": self.symbol,
            "date": self.date,
            "passed": self.passed,
            "detail": self.detail,
            "skipped": self.skipped,
            "allowlisted": self.allowlisted,
        }


@dataclass(frozen=True)
class AllowlistEntry:
    """One acknowledged gap.

    Committed rather than passed at runtime because it doubles as the source for the M9
    writeup's data-caveats section -- a runtime flag would leave the caveats undocumented.
    """

    dataset: str
    symbol: str
    reason: str
    acknowledged: str
    check: str | None = None
    start: str | None = None
    end: str | None = None

    def matches(self, result: CheckResult) -> bool:
        if self.dataset != result.dataset:
            return False
        if self.symbol != result.symbol:
            return False
        if self.check is not None and self.check != result.check:
            return False
        if self.start is None and self.end is None:
            return True
        if result.date is None:
            return False
        if self.start is not None and result.date < self.start:
            return False
        return not (self.end is not None and result.date > self.end)


def load_allowlist(path: Path | None = None) -> list[AllowlistEntry]:
    """Read the committed allowlist. A missing file means nothing is acknowledged."""
    allowlist_path = path if path is not None else ALLOWLIST_PATH
    if not allowlist_path.exists():
        return []

    payload = tomllib.loads(allowlist_path.read_text())
    entries = []
    for raw in payload.get("gap", []):
        missing = {"dataset", "symbol", "reason", "acknowledged"} - set(raw)
        if missing:
            raise ValidationError(
                f"allowlist entry missing {sorted(missing)}: {raw}. Every acknowledged "
                "gap needs a reason and the date someone looked at it -- an unexplained "
                "allowlist entry is the thing this file exists to prevent."
            )
        entries.append(AllowlistEntry(**raw))
    return entries


@dataclass
class Report:
    """Every check's verdict, plus the allowlist that softened some of them."""

    results: list[CheckResult] = field(default_factory=list)

    @property
    def failures(self) -> list[CheckResult]:
        return [r for r in self.results if r.counts_as_failure]

    @property
    def allowlisted(self) -> list[CheckResult]:
        return [r for r in self.results if r.allowlisted]

    @property
    def skipped(self) -> list[CheckResult]:
        return [r for r in self.results if r.skipped]

    @property
    def ok(self) -> bool:
        return not self.failures

    def to_json(self) -> dict:
        return {
            "ok": self.ok,
            "checked": len(self.results),
            "failed": len(self.failures),
            "allowlisted": len(self.allowlisted),
            "skipped": len(self.skipped),
            "results": [r.to_json() for r in self.results],
        }

    def write(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_json(), indent=2) + "\n")
        return path

    def summary(self) -> str:
        lines = [
            f"{'PASS' if self.ok else 'FAIL'}: {len(self.results)} check(s), "
            f"{len(self.failures)} failed, {len(self.allowlisted)} allowlisted, "
            f"{len(self.skipped)} skipped"
        ]
        for result in self.failures:
            scope = ".".join(p for p in (result.dataset, result.symbol, result.date) if p)
            lines.append(f"  FAIL {result.check} [{scope}]: {result.detail}")
        for result in self.allowlisted:
            scope = ".".join(p for p in (result.dataset, result.symbol, result.date) if p)
            lines.append(f"  allowed {result.check} [{scope}]: {result.detail}")
        for result in self.skipped:
            lines.append(f"  skipped {result.check}: {result.detail}")
        return "\n".join(lines)


class Corpus:
    """Read-only view of the stored datasets under one data root."""

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else data_root()

    def dataset_dir(self, dataset: str) -> Path:
        return self.root / DATASET_DIRS[dataset]

    def exists(self, dataset: str) -> bool:
        return self.dataset_dir(dataset).is_dir()

    def symbols(self, dataset: str) -> list[str]:
        if not self.exists(dataset):
            return []
        return sorted(
            p.name.split("=", 1)[1]
            for p in self.dataset_dir(dataset).iterdir()
            if p.is_dir() and p.name.startswith("symbol=")
        )

    def dates(self, dataset: str, symbol: str) -> list[str]:
        base = self.dataset_dir(dataset) / f"symbol={symbol}"
        if not base.is_dir():
            return []
        return sorted(
            p.name.split("=", 1)[1]
            for p in base.iterdir()
            if p.is_dir() and p.name.startswith("date=")
        )

    def read(self, dataset: str, symbol: str, date: str) -> pd.DataFrame:
        """One partition, with its Hive keys restored.

        Reading the leaf directory is far cheaper than scanning the dataset and filtering,
        but the leaf sits *below* the ``symbol=``/``date=`` path segments, so PyArrow has
        nothing to recover the partition columns from. They are re-attached from the path
        -- which is exactly where Hive partitioning reads them from too, so this restores
        the columns rather than inventing them.
        """
        path = self.dataset_dir(dataset) / f"symbol={symbol}" / f"date={date}"
        if not path.is_dir():
            raise ValidationError(f"no partition at {path}")
        frame = read_parquet(path)
        for column, value in (("symbol", symbol), ("date", date)):
            if column not in frame.columns:
                frame[column] = value
        return frame

    def partitions(self, dataset: str) -> Iterator[tuple[str, str]]:
        for symbol in self.symbols(dataset):
            for date in self.dates(dataset, symbol):
                yield symbol, date


@dataclass(frozen=True)
class Config:
    """What the validator was asked to check."""

    start: dt.date | None = None
    end: dt.date | None = None
    #: Network checks are off by default so the gate never depends on a live host (C10).
    verify_checksums: bool = False
    reconcile_volume: bool = False
    #: Symbols expected to trade every day; a structurally empty day is a fetch bug.
    liquid_symbols: tuple[str, ...] = ()


CheckFn = Callable[[Corpus, Config], Iterator[CheckResult]]
CHECKS: dict[str, CheckFn] = {}


def check(name: str) -> Callable[[CheckFn], CheckFn]:
    def register(fn: CheckFn) -> CheckFn:
        CHECKS[name] = fn
        fn.check_name = name  # type: ignore[attr-defined]
        return fn

    return register


def _dates_between(start: dt.date, end: dt.date) -> list[str]:
    out, cursor = [], start
    while cursor <= end:
        out.append(cursor.isoformat())
        cursor += dt.timedelta(days=1)
    return out


# --- Integrity ------------------------------------------------------------------------

EXPECTED_COLUMNS = {
    TRADES: set(fetch_trades.SCHEMA) | {"symbol", "date"},
    FUNDING: set(fetch_funding.SCHEMA) | {"symbol", "date"},
    BOOK: set(fetch_book.SCHEMA.names) | {"symbol", "date"},
    BOOK_SNAPSHOT: set(fetch_book.SNAPSHOT_SCHEMA.names) | {"symbol", "date"},
}


@check("schema")
def check_schema(corpus: Corpus, config: Config) -> Iterator[CheckResult]:
    """Every partition reads back with its Section 3 columns. Catches upstream drift."""
    for dataset in DATASET_DIRS:
        for symbol, date in corpus.partitions(dataset):
            frame = corpus.read(dataset, symbol, date)
            missing = EXPECTED_COLUMNS[dataset] - set(frame.columns)
            yield CheckResult(
                check="schema",
                dataset=dataset,
                symbol=symbol,
                date=date,
                passed=not missing,
                detail="ok" if not missing else f"missing columns {sorted(missing)}",
            )


@check("archive_checksums")
def check_archive_checksums(corpus: Corpus, config: Config) -> Iterator[CheckResult]:
    """Re-verify cached Binance archives against their published checksums.

    Opt-in: this needs the network, and a validator used as a CI gate must not. Reported
    as *skipped* rather than passed when off -- a check that quietly reports success
    without running is precisely the false confidence this module exists to avoid.
    """
    if not config.verify_checksums:
        yield CheckResult(
            check="archive_checksums",
            dataset=TRADES,
            symbol=None,
            date=None,
            passed=True,
            skipped=True,
            detail="not run (needs network; pass --verify-checksums)",
        )
        return

    from perpcarry.ingestion import binance_archive
    from perpcarry.ingestion.download import cache_dir, fetch_checksum, sha256

    cache = cache_dir()
    archives = sorted(cache.glob("*.zip")) if cache.is_dir() else []
    for path in archives:
        url = binance_archive.url_for_filename(path.name)
        if url is None:
            # Reported, not skipped. An unparseable name means this check cannot speak for
            # that file, which is a different thing from the file being sound.
            yield CheckResult(
                check="archive_checksums",
                dataset=TRADES,
                symbol=None,
                date=None,
                passed=False,
                detail=f"{path.name}: cannot reconstruct its source URL to verify against",
            )
            continue

        expected = fetch_checksum(url)
        if expected is None:
            yield CheckResult(
                check="archive_checksums",
                dataset=TRADES,
                symbol=None,
                date=None,
                passed=True,
                skipped=True,
                detail=f"{path.name}: no .CHECKSUM published at {url}",
            )
            continue

        actual = sha256(path)
        yield CheckResult(
            check="archive_checksums",
            dataset=TRADES,
            symbol=None,
            date=None,
            passed=actual == expected,
            detail="ok" if actual == expected else f"{path.name}: {actual} != {expected}",
        )


# --- Completeness ---------------------------------------------------------------------


@check("date_coverage")
def check_date_coverage(corpus: Corpus, config: Config) -> Iterator[CheckResult]:
    """No missing dates per dataset per symbol. A missing day silently shortens the study.

    With no explicit range, interior holes are still detected: the observed min and max
    bound the range, so a day absent between two present ones fails. Only a truncated
    *edge* needs the range to be stated.
    """
    for dataset in DATASET_DIRS:
        first_of_month_only = dataset in {BOOK, BOOK_SNAPSHOT}
        for symbol in corpus.symbols(dataset):
            present = corpus.dates(dataset, symbol)
            if not present:
                continue
            start = config.start or dt.date.fromisoformat(present[0])
            end = config.end or dt.date.fromisoformat(present[-1])

            if first_of_month_only:
                expected = [d.isoformat() for d in tardis.free_tier_days(start, end)]
            else:
                expected = _dates_between(start, end)

            missing = sorted(set(expected) - set(present))
            for date in missing:
                yield CheckResult(
                    check="date_coverage",
                    dataset=dataset,
                    symbol=symbol,
                    date=date,
                    passed=False,
                    detail=f"no partition for {symbol} {date}",
                )
            if not missing:
                yield CheckResult(
                    check="date_coverage",
                    dataset=dataset,
                    symbol=symbol,
                    date=None,
                    passed=True,
                    detail=f"{len(present)} date(s), {present[0]}..{present[-1]}",
                )


@check("funding_settlement_count")
def check_funding_settlement_count(corpus: Corpus, config: Config) -> Iterator[CheckResult]:
    """Settlements per day match ``24 / funding_interval_hours``.

    The interval is read per row rather than assumed: ``0GUSDT`` ran 4h at listing, 1h
    from 2025-09-22, and 4h again by 2026-06, so a per-symbol constant is wrong.
    """
    for symbol, date in corpus.partitions(FUNDING):
        frame = corpus.read(FUNDING, symbol, date)
        if frame.empty:
            continue
        intervals = set(frame["funding_interval_hours"])
        expected = sum(24 // int(h) for h in intervals) // max(len(intervals), 1)
        if len(intervals) > 1:
            # A cadence change inside one day: the exact count is not defined, so only
            # the weaker "at least one settlement" property is checkable here.
            yield CheckResult(
                check="funding_settlement_count",
                dataset=FUNDING,
                symbol=symbol,
                date=date,
                passed=len(frame) > 0,
                detail=f"mixed intervals {sorted(intervals)}, {len(frame)} settlement(s)",
            )
            continue
        yield CheckResult(
            check="funding_settlement_count",
            dataset=FUNDING,
            symbol=symbol,
            date=date,
            passed=len(frame) == expected,
            detail=(
                "ok"
                if len(frame) == expected
                else f"{len(frame)} settlement(s), expected {expected} at {sorted(intervals)[0]}h"
            ),
        )


@check("trade_id_continuity")
def check_trade_id_continuity(corpus: Corpus, config: Config) -> Iterator[CheckResult]:
    """``trade_id`` continuous within each day *and* across day boundaries.

    The across-day half is the one that matters: a wholly missing day between two intact
    days leaves both looking perfect, and only the boundary jump reveals it.

    **Contiguity is not the invariant** -- the design doc's original wording was wrong.
    Binance's `trades` dataset skips isolated ids: 0GUSDT 2026-06 has 154 such skips
    across 2.37M trades and still reconciles *exactly* against klines volume, so nothing
    is lost. Only runs longer than ``fetch_trades.MAX_ID_SKIP`` are treated as loss. Skips
    are still counted and reported, because a rising skip rate would be worth knowing even
    though today's is benign.
    """
    for symbol in corpus.symbols(TRADES):
        previous_last: int | None = None
        previous_date: str | None = None
        for date in corpus.dates(TRADES, symbol):
            frame = corpus.read(TRADES, symbol, date).sort_values("trade_id")
            if frame.empty:
                continue

            skips, losses = fetch_trades.classify_gaps(fetch_trades.trade_id_gaps(frame))
            detail = "ok"
            if losses:
                detail = (
                    f"{len(losses)} gap(s) larger than {fetch_trades.MAX_ID_SKIP} ids, "
                    f"first {losses[0]}"
                )
            elif skips:
                absent = sum(b - a - 1 for a, b in skips)
                detail = f"{len(skips)} venue id-skip(s), {absent} absent id(s)"
            yield CheckResult(
                check="trade_id_continuity",
                dataset=TRADES,
                symbol=symbol,
                date=date,
                passed=not losses,
                detail=detail,
            )

            first_id = int(frame["trade_id"].iloc[0])
            if previous_last is not None:
                absent = first_id - previous_last - 1
                if absent > fetch_trades.MAX_ID_SKIP:
                    yield CheckResult(
                        check="trade_id_continuity",
                        dataset=TRADES,
                        symbol=symbol,
                        date=date,
                        passed=False,
                        detail=(
                            f"boundary gap from {previous_date}: {previous_last} -> {first_id} "
                            f"({absent} trade(s) missing)"
                        ),
                    )
            previous_last = int(frame["trade_id"].iloc[-1])
            previous_date = date


# --- Consistency ----------------------------------------------------------------------


@check("duplicate_trade_ids")
def check_duplicate_trade_ids(corpus: Corpus, config: Config) -> Iterator[CheckResult]:
    """No repeated ``(symbol, trade_id)`` -- the signature of an overlapping re-fetch."""
    for symbol in corpus.symbols(TRADES):
        seen: dict[int, str] = {}
        collisions: list[str] = []
        for date in corpus.dates(TRADES, symbol):
            frame = corpus.read(TRADES, symbol, date)
            within = fetch_trades.duplicate_trade_ids(frame)
            if within:
                collisions.append(f"{date}: {len(within)} within-day duplicate(s)")
            for trade_id in frame["trade_id"]:
                key = int(trade_id)
                if key in seen and seen[key] != date:
                    collisions.append(f"trade_id {key} in both {seen[key]} and {date}")
                seen[key] = date
        yield CheckResult(
            check="duplicate_trade_ids",
            dataset=TRADES,
            symbol=symbol,
            date=None,
            passed=not collisions,
            detail="ok" if not collisions else "; ".join(collisions[:3]),
        )


TIMESTAMP_COLUMNS = {
    TRADES: "timestamp",
    FUNDING: "funding_time",
    BOOK: "timestamp",
    BOOK_SNAPSHOT: "timestamp",
}


@check("timestamp_monotonic")
def check_timestamp_monotonic(corpus: Corpus, config: Config) -> Iterator[CheckResult]:
    """Timestamps non-decreasing within each partition, in the dataset's natural order.

    Trades are ordered by ``trade_id`` and the book by file order; sorting by timestamp
    first would make the check vacuous, since any sequence is monotonic once sorted.
    """
    for dataset, column in TIMESTAMP_COLUMNS.items():
        for symbol, date in corpus.partitions(dataset):
            frame = corpus.read(dataset, symbol, date)
            if frame.empty:
                continue
            if dataset == TRADES:
                frame = frame.sort_values("trade_id")
            series = frame[column]
            monotonic = bool(series.is_monotonic_increasing)
            offenders = int((series.diff() < 0).sum())
            yield CheckResult(
                check="timestamp_monotonic",
                dataset=dataset,
                symbol=symbol,
                date=date,
                passed=monotonic,
                detail="ok" if monotonic else f"{offenders} backward step(s) in {column}",
            )


@check("volume_reconciliation")
def check_volume_reconciliation(corpus: Corpus, config: Config) -> Iterator[CheckResult]:
    """Summed trade quantity equals summed 1m ``klines`` volume, **exactly**.

    An equality rather than a tolerance: measured zero difference across three symbols
    including 1.9M fractional-quantity trades (M1-T4 Q1). A tolerance wide enough to be
    safe would be wide enough to hide a genuinely missing chunk of a day. If this ever
    fails, that is a finding to investigate, not a threshold to widen.

    Opt-in: ``klines`` is not stored in the corpus, so this needs the network.
    """
    if not config.reconcile_volume:
        yield CheckResult(
            check="volume_reconciliation",
            dataset=TRADES,
            symbol=None,
            date=None,
            passed=True,
            skipped=True,
            detail="not run (needs network; pass --reconcile-volume)",
        )
        return

    for symbol, date in corpus.partitions(TRADES):
        frame = corpus.read(TRADES, symbol, date)
        traded = fetch_trades.total_quantity(frame)
        expected = fetch_trades.klines_volume(symbol, date)
        yield CheckResult(
            check="volume_reconciliation",
            dataset=TRADES,
            symbol=symbol,
            date=date,
            passed=traded == expected,
            detail="ok" if traded == expected else f"trades {traded} != klines {expected}",
        )


@check("funding_within_trades_window")
def check_funding_within_trades_window(corpus: Corpus, config: Config) -> Iterator[CheckResult]:
    """Every funding settlement falls inside the trades coverage window.

    Detects the two legs being assembled over mismatched ranges -- which would let the
    backtest earn funding on days it has no execution data for.
    """
    for symbol in corpus.symbols(FUNDING):
        trade_dates = corpus.dates(TRADES, symbol)
        if not trade_dates:
            yield CheckResult(
                check="funding_within_trades_window",
                dataset=FUNDING,
                symbol=symbol,
                date=None,
                passed=False,
                detail=f"{symbol} has funding but no trades at all",
            )
            continue
        first, last = trade_dates[0], trade_dates[-1]
        outside = [d for d in corpus.dates(FUNDING, symbol) if d < first or d > last]
        for date in outside:
            yield CheckResult(
                check="funding_within_trades_window",
                dataset=FUNDING,
                symbol=symbol,
                date=date,
                passed=False,
                detail=f"funding on {date} outside trades window {first}..{last}",
            )
        if not outside:
            yield CheckResult(
                check="funding_within_trades_window",
                dataset=FUNDING,
                symbol=symbol,
                date=None,
                passed=True,
                detail=f"within {first}..{last}",
            )


@check("single_venue")
def check_single_venue(corpus: Corpus, config: Config) -> Iterator[CheckResult]:
    """Every venue-tagged row names the expected venue.

    **What this does and does not cover.** The book datasets carry an ``exchange`` column,
    and they are the only place a venue mix can realistically enter: the vendor's URL
    shape serves every exchange it carries, so a wrong exchange segment yields a perfectly
    valid file from the wrong market. Trades and funding carry no venue field -- their
    venue is fixed by the archive host they can only have come from -- so this check
    cannot confirm them from the data, and says so rather than passing silently.
    """
    checked_any = False
    for dataset in (BOOK, BOOK_SNAPSHOT):
        for symbol, date in corpus.partitions(dataset):
            frame = corpus.read(dataset, symbol, date)
            if "exchange" not in frame.columns or frame.empty:
                continue
            checked_any = True
            venues = {str(v).strip() for v in frame["exchange"].unique()}
            ok = venues == {EXPECTED_VENUE}
            yield CheckResult(
                check="single_venue",
                dataset=dataset,
                symbol=symbol,
                date=date,
                passed=ok,
                detail="ok" if ok else f"expected {EXPECTED_VENUE!r}, found {sorted(venues)}",
            )

    for dataset in (TRADES, FUNDING):
        if corpus.symbols(dataset):
            yield CheckResult(
                check="single_venue",
                dataset=dataset,
                symbol=None,
                date=None,
                passed=True,
                skipped=True,
                detail=(
                    "no venue field in this dataset; venue is established by the archive "
                    "host, not verifiable from stored rows"
                ),
            )
    if not checked_any:
        yield CheckResult(
            check="single_venue",
            dataset=BOOK,
            symbol=None,
            date=None,
            passed=True,
            skipped=True,
            detail="no venue-tagged partitions in the corpus",
        )


# --- Plausibility ---------------------------------------------------------------------


@check("finite_positive")
def check_finite_positive(corpus: Corpus, config: Config) -> Iterator[CheckResult]:
    """Prices and quantities finite, prices positive.

    Quantity is allowed to be **zero in the book datasets only**, where ``amount = 0`` is
    the level-removal convention. Treating those as defects here would either fail every
    real book day or push someone to strip them, which is the exact silent-drift failure
    M1-T3 guards against.
    """
    for dataset in DATASET_DIRS:
        if dataset == FUNDING:
            continue
        allows_zero_quantity = dataset in {BOOK, BOOK_SNAPSHOT}
        for symbol, date in corpus.partitions(dataset):
            frame = corpus.read(dataset, symbol, date)
            if frame.empty:
                continue
            problems = []
            price, quantity = frame["price"], frame["quantity"]
            if not bool(price.notna().all()) or bool((price <= 0).any()):
                problems.append(f"{int((price <= 0).sum() + price.isna().sum())} bad price(s)")
            bad_quantity = quantity.isna() | (quantity < 0)
            if not allows_zero_quantity:
                bad_quantity |= quantity == 0
            if bool(bad_quantity.any()):
                problems.append(f"{int(bad_quantity.sum())} bad quantity(ies)")
            yield CheckResult(
                check="finite_positive",
                dataset=dataset,
                symbol=symbol,
                date=date,
                passed=not problems,
                detail="ok" if not problems else ", ".join(problems),
            )


@check("funding_rate_sanity")
def check_funding_rate_sanity(corpus: Corpus, config: Config) -> Iterator[CheckResult]:
    """Funding rates within a sanity bound.

    Reuses ``fetch_funding.RATE_SANITY_BOUND``. This is deliberately *not* the venue's
    published cap, which cannot be read from here (``/fapi/v1/fundingInfo`` is geo-blocked,
    B-004) -- it is set far above anything observed so it catches corrupt data rather than
    policy edge cases.
    """
    bound = fetch_funding.RATE_SANITY_BOUND
    for symbol, date in corpus.partitions(FUNDING):
        frame = corpus.read(FUNDING, symbol, date)
        if frame.empty:
            continue
        outside = frame[frame["funding_rate"].abs() > bound]
        yield CheckResult(
            check="funding_rate_sanity",
            dataset=FUNDING,
            symbol=symbol,
            date=date,
            passed=outside.empty,
            detail=(
                "ok"
                if outside.empty
                else f"{len(outside)} rate(s) beyond +/-{bound}, worst "
                f"{outside['funding_rate'].abs().max()}"
            ),
        )


@check("no_empty_days")
def check_no_empty_days(corpus: Corpus, config: Config) -> Iterator[CheckResult]:
    """A structurally empty day means a fetch bug, not a quiet market.

    Applied to every symbol for the book datasets and to ``config.liquid_symbols`` for
    trades: a thin altcoin genuinely can have a zero-trade day, and failing that would
    train whoever runs this to ignore the output.
    """
    for dataset in DATASET_DIRS:
        for symbol, date in corpus.partitions(dataset):
            if dataset == TRADES and symbol not in config.liquid_symbols:
                continue
            frame = corpus.read(dataset, symbol, date)
            yield CheckResult(
                check="no_empty_days",
                dataset=dataset,
                symbol=symbol,
                date=date,
                passed=not frame.empty,
                detail="ok" if not frame.empty else "partition has zero rows",
            )


# --- Order book -----------------------------------------------------------------------


@check("book_opens_with_snapshot")
def check_book_opens_with_snapshot(corpus: Corpus, config: Config) -> Iterator[CheckResult]:
    """Without an opening image the day cannot be replayed from a known state."""
    for symbol, date in corpus.partitions(BOOK):
        frame = corpus.read(BOOK, symbol, date).sort_values("timestamp", kind="stable")
        if frame.empty:
            continue
        opens = bool(frame["is_snapshot"].iloc[0])
        yield CheckResult(
            check="book_opens_with_snapshot",
            dataset=BOOK,
            symbol=symbol,
            date=date,
            passed=opens,
            detail="ok" if opens else "first row is not a snapshot",
        )


@check("book_has_removals")
def check_book_has_removals(corpus: Corpus, config: Config) -> Iterator[CheckResult]:
    """``amount = 0`` rows present.

    Their absence means an upstream clean step dropped level removals -- after which the
    replayed book accumulates phantom levels and drifts without ever raising.
    """
    for symbol, date in corpus.partitions(BOOK):
        frame = corpus.read(BOOK, symbol, date)
        if frame.empty:
            continue
        removals = int((frame["quantity"] == 0).sum())
        yield CheckResult(
            check="book_has_removals",
            dataset=BOOK,
            symbol=symbol,
            date=date,
            passed=removals > 0,
            detail=f"{removals} removal(s)" if removals else "no amount=0 rows -- dropped?",
        )


@check("book_reference_pairing")
def check_book_reference_pairing(corpus: Corpus, config: Config) -> Iterator[CheckResult]:
    """Book days are first-of-month only and each has a matching reference snapshot.

    A missing ``book_snapshot_25`` makes M2-T2 unverifiable, and since this feed carries
    no sequence number that reference is the *only* independent check on replay.
    """
    for symbol, date in corpus.partitions(BOOK):
        first_of_month = dt.date.fromisoformat(date).day == 1
        yield CheckResult(
            check="book_reference_pairing",
            dataset=BOOK,
            symbol=symbol,
            date=date,
            passed=first_of_month,
            detail="ok" if first_of_month else f"{date} is not a first-of-month free-tier day",
        )
        paired = date in corpus.dates(BOOK_SNAPSHOT, symbol)
        yield CheckResult(
            check="book_reference_pairing",
            dataset=BOOK_SNAPSHOT,
            symbol=symbol,
            date=date,
            passed=paired,
            detail="ok" if paired else f"no book_snapshot_25 for {symbol} {date}",
        )


@check("book_within_trades_window")
def check_book_within_trades_window(corpus: Corpus, config: Config) -> Iterator[CheckResult]:
    """Book coverage inside the trades window.

    Calibrating the impact model on a period the backtest never sees would fit costs to
    one market regime and spend them in another.
    """
    for symbol in corpus.symbols(BOOK):
        trade_dates = corpus.dates(TRADES, symbol)
        if not trade_dates:
            yield CheckResult(
                check="book_within_trades_window",
                dataset=BOOK,
                symbol=symbol,
                date=None,
                passed=False,
                detail=f"{symbol} has book data but no trades at all",
            )
            continue
        first, last = trade_dates[0], trade_dates[-1]
        outside = [d for d in corpus.dates(BOOK, symbol) if d < first or d > last]
        for date in outside:
            yield CheckResult(
                check="book_within_trades_window",
                dataset=BOOK,
                symbol=symbol,
                date=date,
                passed=False,
                detail=f"book on {date} outside trades window {first}..{last}",
            )
        if not outside:
            yield CheckResult(
                check="book_within_trades_window",
                dataset=BOOK,
                symbol=symbol,
                date=None,
                passed=True,
                detail=f"within {first}..{last}",
            )


# --- Driver ---------------------------------------------------------------------------


def validate(
    corpus: Corpus,
    config: Config | None = None,
    *,
    checks: Sequence[str] | None = None,
    allowlist: Sequence[AllowlistEntry] | None = None,
) -> Report:
    """Run every check (or a named subset) and fold the allowlist over the results."""
    config = config or Config()
    entries = list(allowlist) if allowlist is not None else load_allowlist()
    names = list(checks) if checks is not None else list(CHECKS)

    unknown = sorted(set(names) - set(CHECKS))
    if unknown:
        raise ValidationError(f"unknown check(s) {unknown}; known: {sorted(CHECKS)}")

    report = Report()
    for name in names:
        for result in CHECKS[name](corpus, config):
            if result.counts_as_failure and any(e.matches(result) for e in entries):
                result = CheckResult(**{**result.__dict__, "allowlisted": True})
            report.results.append(result)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the assembled research corpus")
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--start", type=dt.date.fromisoformat)
    parser.add_argument("--end", type=dt.date.fromisoformat)
    parser.add_argument("--check", action="append", choices=sorted(CHECKS))
    parser.add_argument("--liquid", action="append", default=[])
    parser.add_argument("--verify-checksums", action="store_true")
    parser.add_argument("--reconcile-volume", action="store_true")
    parser.add_argument("--report", type=Path, help="write the JSON report here")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    report = validate(
        Corpus(args.root),
        Config(
            start=args.start,
            end=args.end,
            verify_checksums=args.verify_checksums,
            reconcile_volume=args.reconcile_volume,
            liquid_symbols=tuple(args.liquid),
        ),
        checks=args.check,
    )
    print(report.summary())
    if args.report:
        report.write(args.report)
        log.info("wrote %s", args.report)
    return 0 if report.ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
