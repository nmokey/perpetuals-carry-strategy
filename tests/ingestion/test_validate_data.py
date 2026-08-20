"""M1-T4 acceptance tests.

The shape of this file is dictated by the task: a validator that cannot be *shown* to fail
on known-bad input provides false confidence, which is worse than no validator. So the
core of it is one clean synthetic corpus, one corruption per check, and an assertion that
the corruption trips exactly the checks it should and no others.

Where a corruption legitimately trips more than one check, the expected set says so and
the test explains why -- a coupled pair is a fact about the data, but an *unexplained*
coupled pair usually means a check is over-reaching.

Fixtures are synthetic. Vendor book rows may never be committed (M1-T3 licence), and the
Binance-derived fixtures used elsewhere carry no venue field to test with.
"""

import datetime as dt
import shutil

import pandas as pd
import pytest

from perpcarry.ingestion import fetch_funding, fetch_trades
from perpcarry.ingestion.validate_data import (
    BOOK,
    BOOK_SNAPSHOT,
    CHECKS,
    FUNDING,
    TRADES,
    AllowlistEntry,
    CheckResult,
    Config,
    Corpus,
    ValidationError,
    load_allowlist,
    validate,
)
from perpcarry.storage import write_parquet

SYMBOL = "0GUSDT"
DAY1 = "2026-06-01"
DAY2 = "2026-06-02"
VENUE = "binance-futures"


def ms(date: str, hour: int = 0, minute: int = 0) -> int:
    moment = dt.datetime.fromisoformat(date).replace(hour=hour, minute=minute, tzinfo=dt.UTC)
    return int(moment.timestamp() * 1000)


def trades_frame(date: str, *, first_id: int, n: int = 10, symbol: str = SYMBOL) -> pd.DataFrame:
    return pd.DataFrame(
        {
            # Minutes, not hours: n can exceed 24 when a test needs a long day.
            "timestamp": [ms(date, minute=i) for i in range(n)],
            "trade_id": list(range(first_id, first_id + n)),
            "symbol": symbol,
            "price": [0.14 + i * 0.0001 for i in range(n)],
            "quantity": [100.0 + i for i in range(n)],
            "side": ["buy" if i % 2 else "sell" for i in range(n)],
            "date": date,
        }
    )


def funding_frame(date: str, *, interval: int = 4, symbol: str = SYMBOL) -> pd.DataFrame:
    per_day = 24 // interval
    return pd.DataFrame(
        {
            "funding_time": [ms(date, hour=i * interval) for i in range(per_day)],
            "symbol": symbol,
            "funding_rate": [0.0001 * (i + 1) for i in range(per_day)],
            "funding_interval_hours": interval,
            "date": date,
        }
    )


def book_frame(date: str, *, symbol: str = SYMBOL, venue: str = VENUE) -> pd.DataFrame:
    rows = []
    for i in range(4):  # opening snapshot block
        rows.append((True, "bid", 0.14 + i * 0.0001, 100.0 + i))
    rows.append((False, "ask", 0.15, 50.0))
    rows.append((False, "bid", 0.1399, 0.0))  # a removal
    return pd.DataFrame(
        {
            "exchange": venue,
            "timestamp": [ms(date, minute=i) for i in range(len(rows))],
            "local_timestamp": [ms(date, minute=i) + 2 for i in range(len(rows))],
            "latency_us": [2041] * len(rows),
            "is_snapshot": [r[0] for r in rows],
            "side": [r[1] for r in rows],
            "price": [r[2] for r in rows],
            "quantity": [r[3] for r in rows],
            "symbol": symbol,
            "date": date,
        }
    )


def snapshot_frame(date: str, *, symbol: str = SYMBOL, venue: str = VENUE) -> pd.DataFrame:
    levels = list(range(3))
    return pd.DataFrame(
        {
            "exchange": venue,
            "timestamp": [ms(date, minute=1)] * (2 * len(levels)),
            "local_timestamp": [ms(date, minute=1) + 2] * (2 * len(levels)),
            "latency_us": [2041] * (2 * len(levels)),
            "side": ["ask"] * len(levels) + ["bid"] * len(levels),
            "level": levels + levels,
            "price": [0.15 + i * 0.0001 for i in levels] + [0.14 - i * 0.0001 for i in levels],
            "quantity": [10.0 + i for i in levels] * 2,
            "symbol": symbol,
            "date": date,
        }
    )


def build_corpus(root) -> Corpus:
    """A clean corpus: two trade days, two funding days, one book day plus its reference.

    Written through the fetchers' own ``store`` functions rather than to hand-written
    paths. That is not tidiness. An earlier version of this fixture hard-coded
    ``fundingRate/`` while ``fetch_funding`` actually writes ``funding/``, so the validator
    was pointed at a directory that existed only in the tests: everything passed while the
    real corpus went entirely unchecked. Deriving the layout from the code under test is
    what makes that class of drift fail loudly.
    """
    root.mkdir(parents=True, exist_ok=True)
    fetch_trades.store(
        pd.concat([trades_frame(DAY1, first_id=1000), trades_frame(DAY2, first_id=1010)]),
        root=root,
    )
    fetch_funding.store(pd.concat([funding_frame(DAY1), funding_frame(DAY2)]), root=root)
    write_parquet(book_frame(DAY1), root / BOOK, partition_cols=["symbol", "date"])
    write_parquet(snapshot_frame(DAY1), root / BOOK_SNAPSHOT, partition_cols=["symbol", "date"])
    return Corpus(root)


def test_the_fixture_layout_matches_where_the_fetchers_actually_write(tmp_path):
    """The guard for the bug described in build_corpus.

    If a fetcher's storage directory moves, the validator's constants and this fixture
    must move with it -- and this fails if any of the three drift apart.
    """
    corpus = build_corpus(tmp_path / "corpus")

    for dataset in (TRADES, FUNDING, BOOK, BOOK_SNAPSHOT):
        assert corpus.symbols(dataset) == [SYMBOL], f"{dataset} is not where the validator looks"


@pytest.fixture
def corpus(tmp_path) -> Corpus:
    return build_corpus(tmp_path / "corpus")


def failing(corpus: Corpus, config: Config | None = None, allowlist=()) -> set[str]:
    report = validate(corpus, config, allowlist=allowlist)
    return {r.check for r in report.failures}


def partition(corpus: Corpus, dataset: str, date: str, symbol: str = SYMBOL):
    return corpus.dataset_dir(dataset) / f"symbol={symbol}" / f"date={date}"


def rewrite(corpus: Corpus, dataset: str, date: str, frame: pd.DataFrame) -> None:
    """Replace one partition's contents with ``frame``."""
    target = partition(corpus, dataset, date)
    shutil.rmtree(target)
    write_parquet(frame, corpus.dataset_dir(dataset), partition_cols=["symbol", "date"])


# --- Test 2: a clean corpus passes everything ------------------------------------------


def test_a_clean_corpus_passes_every_check(corpus):
    report = validate(corpus, allowlist=())

    assert report.ok
    assert report.failures == []


def test_a_clean_corpus_exits_zero(corpus):
    from perpcarry.ingestion.validate_data import main

    assert main(["--root", str(corpus.root)]) == 0


def test_every_registered_check_actually_runs_on_the_clean_corpus(corpus):
    """Guards the fixture as much as the code.

    A check that yields nothing on a populated corpus is not passing -- it is not running,
    and would go on not running after the data it guards breaks.
    """
    report = validate(corpus, allowlist=())
    ran = {r.check for r in report.results}

    assert ran == set(CHECKS), f"never produced a result: {sorted(set(CHECKS) - ran)}"


# --- Test 1: each check fires on exactly its own corruption -----------------------------


def test_schema_fires_when_a_column_disappears(corpus):
    frame = book_frame(DAY1).drop(columns=["latency_us"])
    rewrite(corpus, BOOK, DAY1, frame)

    assert failing(corpus) == {"schema"}


def test_date_coverage_fires_on_an_interior_hole(corpus):
    """Three funding days with the middle one missing: the edges cannot explain it."""
    write_parquet(
        funding_frame("2026-06-03"),
        corpus.dataset_dir(FUNDING),
        partition_cols=["symbol", "date"],
    )
    shutil.rmtree(partition(corpus, FUNDING, DAY2))

    assert failing(corpus) == {"date_coverage", "funding_within_trades_window"}


def test_funding_settlement_count_fires_on_a_missing_settlement(corpus):
    frame = funding_frame(DAY1).iloc[:-1]  # 5 settlements where 4h implies 6
    rewrite(corpus, FUNDING, DAY1, frame)

    assert failing(corpus) == {"funding_settlement_count"}


def test_trade_id_continuity_fires_on_a_within_day_loss(corpus):
    """Dropped trades, not renumbered ones, and enough of them to count as loss.

    Renumbering an id also reorders the day when sorted by ``trade_id``, so it trips the
    monotonic check too -- a corruption that tests two things at once tests neither
    precisely. And a *single* dropped id is venue behaviour rather than loss, so the run
    has to exceed MAX_ID_SKIP to be a defect at all.
    """
    rewrite(corpus, TRADES, DAY1, trades_frame(DAY1, first_id=1000, n=30).drop(index=range(10, 22)))
    rewrite(corpus, TRADES, DAY2, trades_frame(DAY2, first_id=1030))

    assert failing(corpus) == {"trade_id_continuity"}


def test_an_isolated_venue_id_skip_is_reported_but_does_not_fail(corpus):
    """Binance skips isolated trade ids and the volume still reconciles exactly.

    Failing on those would reject sound data -- 0GUSDT 2026-06 has 154 of them across
    2.37M trades. They are still surfaced in the detail, because a rising skip rate would
    be worth noticing even though today's is benign.
    """
    rewrite(corpus, TRADES, DAY1, trades_frame(DAY1, first_id=1000).drop(index=5))

    report = validate(corpus, allowlist=())
    continuity = [r for r in report.results if r.check == "trade_id_continuity"]

    assert report.ok
    assert any("venue id-skip" in r.detail for r in continuity)


def test_duplicate_trade_ids_fires_on_an_overlapping_refetch(corpus):
    frame = trades_frame(DAY2, first_id=1010)
    frame.loc[0, "trade_id"] = 1005  # already present on DAY1
    rewrite(corpus, TRADES, DAY2, frame)

    assert failing(corpus) == {"duplicate_trade_ids"}


def test_timestamp_monotonic_fires_on_a_backward_step(corpus):
    frame = trades_frame(DAY1, first_id=1000)
    frame.loc[5, "timestamp"] = ms(DAY1, hour=1)
    rewrite(corpus, TRADES, DAY1, frame)

    assert failing(corpus) == {"timestamp_monotonic"}


def test_funding_within_trades_window_fires_when_the_legs_mismatch(corpus):
    write_parquet(
        funding_frame("2026-07-01"),
        corpus.dataset_dir(FUNDING),
        partition_cols=["symbol", "date"],
    )

    # A funding day past the trades window is also, unavoidably, a coverage hole for
    # every day between -- the same mismatch counted two ways.
    assert failing(corpus) == {"funding_within_trades_window", "date_coverage"}


def test_single_venue_fires_on_a_mixed_venue_corpus(corpus):
    rewrite(corpus, BOOK, DAY1, book_frame(DAY1, venue="okex-futures"))

    assert failing(corpus) == {"single_venue"}


def test_finite_positive_fires_on_a_negative_price(corpus):
    frame = trades_frame(DAY1, first_id=1000)
    frame.loc[3, "price"] = -1.0
    rewrite(corpus, TRADES, DAY1, frame)

    assert failing(corpus) == {"finite_positive"}


def test_finite_positive_fires_on_a_zero_trade_quantity(corpus):
    frame = trades_frame(DAY1, first_id=1000)
    frame.loc[3, "quantity"] = 0.0
    rewrite(corpus, TRADES, DAY1, frame)

    assert failing(corpus) == {"finite_positive"}


def test_funding_rate_sanity_fires_on_an_absurd_rate(corpus):
    frame = funding_frame(DAY1)
    frame.loc[2, "funding_rate"] = 0.9
    rewrite(corpus, FUNDING, DAY1, frame)

    assert failing(corpus) == {"funding_rate_sanity"}


def test_book_opens_with_snapshot_fires_when_the_image_is_missing(corpus):
    frame = book_frame(DAY1)
    frame.loc[0, "is_snapshot"] = False
    rewrite(corpus, BOOK, DAY1, frame)

    assert failing(corpus) == {"book_opens_with_snapshot"}


def test_book_has_removals_fires_when_removals_were_stripped(corpus):
    frame = book_frame(DAY1)
    frame = frame[frame["quantity"] > 0]
    rewrite(corpus, BOOK, DAY1, frame)

    assert failing(corpus) == {"book_has_removals"}


def test_book_reference_pairing_fires_when_the_reference_is_missing(corpus):
    shutil.rmtree(partition(corpus, BOOK_SNAPSHOT, DAY1))

    assert failing(corpus) == {"book_reference_pairing"}


def test_book_reference_pairing_fires_on_a_non_first_of_month_day(corpus):
    write_parquet(book_frame(DAY2), corpus.dataset_dir(BOOK), partition_cols=["symbol", "date"])
    write_parquet(
        snapshot_frame(DAY2),
        corpus.dataset_dir(BOOK_SNAPSHOT),
        partition_cols=["symbol", "date"],
    )

    assert failing(corpus) == {"book_reference_pairing"}


def test_book_within_trades_window_fires_when_the_book_is_outside(corpus):
    """A book month the backtest has no execution data for."""
    write_parquet(
        book_frame("2026-07-01"), corpus.dataset_dir(BOOK), partition_cols=["symbol", "date"]
    )
    write_parquet(
        snapshot_frame("2026-07-01"),
        corpus.dataset_dir(BOOK_SNAPSHOT),
        partition_cols=["symbol", "date"],
    )

    assert failing(corpus) == {"book_within_trades_window"}


def empty_partition(corpus: Corpus, dataset: str, date: str, template: pd.DataFrame) -> None:
    """Leave a partition present but holding zero rows.

    Deleting the directory instead would be a *coverage* defect; this is the different
    failure the check exists for -- a fetch that produced a file with nothing in it.
    """
    target = partition(corpus, dataset, date)
    shutil.rmtree(target)
    target.mkdir(parents=True)
    write_parquet(template.iloc[:0].drop(columns=["symbol", "date"]), target / "part-0.parquet")


def test_no_empty_days_fires_for_a_symbol_declared_liquid(corpus):
    empty_partition(corpus, TRADES, DAY2, trades_frame(DAY2, first_id=1010))
    config = Config(liquid_symbols=(SYMBOL,))

    assert failing(corpus, config) == {"no_empty_days"}


def test_a_thin_symbol_may_have_an_empty_day(corpus):
    """Not declaring a symbol liquid means a zero-trade day is a market fact.

    Failing every quiet altcoin day would train whoever runs this to ignore the output,
    which is how a validator stops working without anyone changing it.
    """
    empty_partition(corpus, TRADES, DAY2, trades_frame(DAY2, first_id=1010))

    assert "no_empty_days" not in failing(corpus)


# --- Test 4: a wholly missing day between two intact days -------------------------------


def test_a_wholly_missing_day_between_two_intact_days_is_caught(corpus):
    """The case per-day checks cannot see: both neighbours look perfect.

    Only the ``trade_id`` jump across the boundary reveals it, which is why the check
    carries state between partitions instead of validating each in isolation.
    """
    write_parquet(
        trades_frame("2026-06-03", first_id=1020),
        corpus.dataset_dir(TRADES),
        partition_cols=["symbol", "date"],
    )
    shutil.rmtree(partition(corpus, TRADES, DAY2))

    report = validate(corpus, allowlist=())
    continuity = [r for r in report.failures if r.check == "trade_id_continuity"]

    assert continuity, "a missing day left no trace in trade_id continuity"
    assert "1009 -> 1020" in continuity[0].detail
    assert "10 trade(s) missing" in continuity[0].detail


def test_each_partition_alone_would_have_looked_perfect(corpus):
    """Shows the above is not detectable per-day -- the point of the across-day check."""
    write_parquet(
        trades_frame("2026-06-03", first_id=1020),
        corpus.dataset_dir(TRADES),
        partition_cols=["symbol", "date"],
    )
    shutil.rmtree(partition(corpus, TRADES, DAY2))

    for date in (DAY1, "2026-06-03"):
        frame = corpus.read(TRADES, SYMBOL, date).sort_values("trade_id")
        assert (frame["trade_id"].diff().dropna() == 1).all()


# --- Test 3: the report names the offending scope and round-trips -----------------------


def test_the_report_names_the_offending_dataset_symbol_and_date(corpus):
    frame = book_frame(DAY1)
    frame.loc[0, "is_snapshot"] = False
    rewrite(corpus, BOOK, DAY1, frame)

    failure = validate(corpus, allowlist=()).failures[0]

    assert (failure.dataset, failure.symbol, failure.date) == (BOOK, SYMBOL, DAY1)
    assert failure.detail


def test_the_report_round_trips_through_json(corpus, tmp_path):
    import json

    frame = funding_frame(DAY1).iloc[:-1]
    rewrite(corpus, FUNDING, DAY1, frame)
    report = validate(corpus, allowlist=())

    path = report.write(tmp_path / "report.json")
    payload = json.loads(path.read_text())

    assert payload["ok"] is False
    assert payload["failed"] == len(report.failures)
    assert payload["checked"] == len(report.results)
    offending = [r for r in payload["results"] if not r["passed"] and not r["allowlisted"]]
    assert offending[0]["check"] == "funding_settlement_count"
    assert offending[0]["date"] == DAY1


def test_the_summary_lists_each_failure(corpus):
    frame = funding_frame(DAY1).iloc[:-1]
    rewrite(corpus, FUNDING, DAY1, frame)

    summary = validate(corpus, allowlist=()).summary()

    assert summary.startswith("FAIL")
    assert "funding_settlement_count" in summary
    assert DAY1 in summary


def test_a_failing_corpus_exits_non_zero(corpus):
    from perpcarry.ingestion.validate_data import main

    frame = funding_frame(DAY1).iloc[:-1]
    rewrite(corpus, FUNDING, DAY1, frame)

    assert main(["--root", str(corpus.root)]) == 1


# --- The allowlist ----------------------------------------------------------------------


def test_an_acknowledged_gap_does_not_fail_the_gate(corpus):
    frame = funding_frame(DAY1).iloc[:-1]
    rewrite(corpus, FUNDING, DAY1, frame)
    entry = AllowlistEntry(
        dataset=FUNDING,
        symbol=SYMBOL,
        check="funding_settlement_count",
        start=DAY1,
        end=DAY1,
        reason="upstream hole, verified against the archive",
        acknowledged="2026-08-20",
    )

    report = validate(corpus, allowlist=[entry])

    assert report.ok
    assert len(report.allowlisted) == 1


def test_an_acknowledged_gap_is_still_reported(corpus):
    """Allowlisted is not the same as invisible.

    The entry exists so the M9 writeup can state the gap factually; a silenced check
    would leave nothing to state.
    """
    frame = funding_frame(DAY1).iloc[:-1]
    rewrite(corpus, FUNDING, DAY1, frame)
    entry = AllowlistEntry(
        dataset=FUNDING,
        symbol=SYMBOL,
        check="funding_settlement_count",
        reason="r",
        acknowledged="2026-08-20",
    )

    report = validate(corpus, allowlist=[entry])

    assert "allowed funding_settlement_count" in report.summary()
    assert report.to_json()["allowlisted"] == 1


def test_an_allowlist_entry_does_not_cover_a_different_date(corpus):
    frame = funding_frame(DAY2).iloc[:-1]
    rewrite(corpus, FUNDING, DAY2, frame)
    entry = AllowlistEntry(
        dataset=FUNDING,
        symbol=SYMBOL,
        check="funding_settlement_count",
        start=DAY1,
        end=DAY1,
        reason="r",
        acknowledged="2026-08-20",
    )

    assert not validate(corpus, allowlist=[entry]).ok


def test_an_allowlist_entry_does_not_cover_a_different_check(corpus):
    frame = book_frame(DAY1)
    frame.loc[0, "is_snapshot"] = False
    rewrite(corpus, BOOK, DAY1, frame)
    entry = AllowlistEntry(
        dataset="book",
        symbol=SYMBOL,
        check="book_has_removals",
        reason="r",
        acknowledged="2026-08-20",
    )

    assert not validate(corpus, allowlist=[entry]).ok


def test_an_allowlist_entry_does_not_cover_a_different_symbol(corpus):
    frame = funding_frame(DAY1).iloc[:-1]
    rewrite(corpus, FUNDING, DAY1, frame)
    entry = AllowlistEntry(
        dataset=FUNDING,
        symbol="ETHUSDT",
        check="funding_settlement_count",
        reason="r",
        acknowledged="2026-08-20",
    )

    assert not validate(corpus, allowlist=[entry]).ok


def test_an_entry_without_a_reason_is_refused(tmp_path):
    """An unexplained allowlist entry is the thing this file exists to prevent."""
    path = tmp_path / "allow.toml"
    path.write_text('[[gap]]\ndataset = "trades"\nsymbol = "0GUSDT"\nacknowledged = "2026-08-20"\n')

    with pytest.raises(ValidationError, match="reason"):
        load_allowlist(path)


def test_a_missing_allowlist_file_acknowledges_nothing(tmp_path):
    assert load_allowlist(tmp_path / "absent.toml") == []


def test_the_committed_allowlist_parses_and_is_fully_documented():
    entries = load_allowlist()

    assert entries, "the known 1000BONKUSDT gap should be acknowledged"
    for entry in entries:
        assert entry.reason.strip(), f"{entry.symbol} has no reason"
        assert dt.date.fromisoformat(entry.acknowledged)
        assert entry.dataset in {TRADES, FUNDING, "book", BOOK_SNAPSHOT}


# --- Network checks are skipped, not silently passed ------------------------------------


def test_network_checks_are_skipped_by_default(corpus):
    report = validate(corpus, allowlist=())
    skipped = {r.check for r in report.skipped}

    assert {"archive_checksums", "volume_reconciliation"} <= skipped


def test_a_skipped_check_is_not_counted_as_a_pass(corpus):
    """A check that reports success without running is the false confidence to avoid."""
    report = validate(corpus, allowlist=())
    skipped = [r for r in report.skipped if r.check == "volume_reconciliation"]

    assert skipped
    assert "not run" in skipped[0].detail
    assert report.to_json()["skipped"] >= 2


def test_a_skipped_result_does_not_count_as_a_failure():
    result = CheckResult(
        check="x",
        dataset=TRADES,
        symbol=None,
        date=None,
        passed=True,
        skipped=True,
        detail="",
    )
    assert not result.counts_as_failure


# --- Driver ------------------------------------------------------------------------------


def test_a_single_check_can_be_run_in_isolation(corpus):
    frame = book_frame(DAY1)
    frame.loc[0, "is_snapshot"] = False
    rewrite(corpus, BOOK, DAY1, frame)

    report = validate(corpus, checks=["book_opens_with_snapshot"])

    assert {r.check for r in report.results} == {"book_opens_with_snapshot"}
    assert not report.ok


def test_an_unknown_check_name_is_refused(corpus):
    with pytest.raises(ValidationError, match="unknown check"):
        validate(corpus, checks=["no_such_check"])


def test_an_empty_corpus_produces_no_failures(tmp_path):
    """Nothing to validate is not the same as invalid -- but it must not read as a pass.

    The report is empty rather than green-with-content, which the summary makes visible.
    """
    report = validate(Corpus(tmp_path / "empty"), allowlist=())

    assert report.ok
    assert report.failures == []


# --- The checksum check must not be a no-op --------------------------------------------


def test_cached_archive_names_reconstruct_their_source_urls():
    """The bug this guards: a wrong URL 404s, the digest comes back None, and the loop
    skips every file -- so the check yields nothing and reads as a clean pass.

    Klines are the shape that breaks a naive parser: they name their *interval* where
    every other dataset names itself.
    """
    from perpcarry.ingestion.binance_archive import url_for_filename

    assert url_for_filename("0GUSDT-trades-2026-06.zip").endswith(
        "/monthly/trades/0GUSDT/0GUSDT-trades-2026-06.zip"
    )
    assert url_for_filename("0GUSDT-trades-2026-06-01.zip").endswith(
        "/daily/trades/0GUSDT/0GUSDT-trades-2026-06-01.zip"
    )
    assert url_for_filename("BTCUSDT-fundingRate-2026-06.zip").endswith(
        "/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2026-06.zip"
    )
    assert url_for_filename("0GUSDT-1m-2026-06-01.zip").endswith(
        "/daily/klines/0GUSDT/1m/0GUSDT-1m-2026-06-01.zip"
    )


def test_an_unparseable_archive_name_is_reported_not_skipped():
    from perpcarry.ingestion.binance_archive import url_for_filename

    assert url_for_filename("garbage.zip") is None
    assert url_for_filename("0GUSDT-trades-notadate.zip") is None


def test_a_file_the_check_cannot_verify_fails_rather_than_vanishing(corpus, monkeypatch, tmp_path):
    """Being unable to verify a file is not the same as the file being sound."""
    from perpcarry.ingestion import download

    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "garbage.zip").write_bytes(b"x")
    monkeypatch.setattr(download, "cache_dir", lambda: cache)

    report = validate(corpus, Config(verify_checksums=True), checks=["archive_checksums"])

    assert not report.ok
    assert "cannot reconstruct" in report.failures[0].detail
