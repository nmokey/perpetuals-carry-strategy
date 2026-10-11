"""M4-T3 -- expressing an order size in comparable units.

Every fixture is synthetic and written here. The one test that reads real data is marked
``network``: it is D-022's cross-check, and it is the only thing in this project that could notice
a trades ingest which silently dropped rows.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from perpcarry.ingestion import fetch_trades
from perpcarry.models import order_size
from perpcarry.storage import write_parquet


def seed_trades(root, symbol: str, per_day: dict[str, list[float]]) -> None:
    """Write synthetic trades through the writer's own path helper, never a restated layout."""
    rows = []
    for day, quantities in per_day.items():
        base = int(dt.datetime.fromisoformat(day).replace(tzinfo=dt.UTC).timestamp() * 1000)
        for i, quantity in enumerate(quantities):
            rows.append(
                {
                    "timestamp": base + i,
                    "trade_id": i,
                    "symbol": symbol,
                    "price": 0.42,
                    "quantity": quantity,
                    "side": "buy",
                    "date": day,
                }
            )
    frame = pd.DataFrame(rows)
    write_parquet(frame, root / fetch_trades.STORAGE_DIR, partition_cols=["symbol", "date"])


def test_daily_volume_is_the_sum_of_that_day_s_quantities(isolated_data_root):
    seed_trades(
        isolated_data_root,
        "TESTUSDT",
        {"2026-06-01": [1.0, 2.0, 3.0], "2026-06-02": [10.0, 5.0]},
    )

    volumes = order_size.daily_volumes("TESTUSDT", root=isolated_data_root)

    assert volumes["2026-06-01"] == pytest.approx(6.0)
    assert volumes["2026-06-02"] == pytest.approx(15.0)


def test_adv_is_the_mean_of_the_days_before_as_of(isolated_data_root):
    seed_trades(
        isolated_data_root,
        "TESTUSDT",
        {
            "2026-06-01": [10.0],
            "2026-06-02": [20.0],
            "2026-06-03": [30.0],
            "2026-06-04": [1000.0],  # the as_of day itself
        },
    )

    adv = order_size.average_daily_volume("TESTUSDT", "2026-06-04", days=3, root=isolated_data_root)

    assert adv == pytest.approx(20.0)  # (10 + 20 + 30) / 3


def test_adv_excludes_the_as_of_day_itself(isolated_data_root):
    """The look-ahead trap, and the natural way to write this function.

    A day's completed volume is not knowable until the day ends, so a decision made *during*
    2026-06-04 may not use 2026-06-04's total. Ranked first among the things that invalidate this
    work, and cheap to get wrong by one day.
    """
    seed_trades(
        isolated_data_root,
        "TESTUSDT",
        {"2026-06-01": [10.0], "2026-06-02": [10.0], "2026-06-03": [10.0], "2026-06-04": [9999.0]},
    )

    adv = order_size.average_daily_volume("TESTUSDT", "2026-06-04", days=3, root=isolated_data_root)

    assert adv == pytest.approx(10.0)
    assert adv < 100.0, "the as_of day's volume leaked into its own ADV"


def test_adv_ignores_days_outside_the_window(isolated_data_root):
    seed_trades(
        isolated_data_root,
        "TESTUSDT",
        {
            "2026-05-01": [100000.0],  # far outside a 3-day window
            "2026-06-01": [10.0],
            "2026-06-02": [20.0],
            "2026-06-03": [30.0],
        },
    )

    adv = order_size.average_daily_volume("TESTUSDT", "2026-06-04", days=3, root=isolated_data_root)

    assert adv == pytest.approx(20.0)


@pytest.mark.parametrize("missing_day", ["2026-06-01", "2026-06-02", "2026-06-03"])
def test_adv_rejects_an_incomplete_window(isolated_data_root, missing_day):
    seed_trades(
        isolated_data_root,
        "TESTUSDT",
        {day: [10.0] for day in ["2026-06-01", "2026-06-02", "2026-06-03"] if day != missing_day},
    )
    with pytest.raises(order_size.OrderSizeError, match=f"missing days:.*{missing_day}"):
        order_size.average_daily_volume("TESTUSDT", "2026-06-04", days=3, root=isolated_data_root)


@pytest.mark.parametrize("quantity", [0.0, -1.0, float("nan"), float("inf")])
def test_adv_rejects_invalid_daily_volume(isolated_data_root, quantity):
    seed_trades(isolated_data_root, "TESTUSDT", {"2026-06-01": [quantity]})
    with pytest.raises(order_size.OrderSizeError, match="invalid daily volumes"):
        order_size.average_daily_volume("TESTUSDT", "2026-06-02", days=1, root=isolated_data_root)


def test_a_size_round_trips_through_the_adv_fraction(isolated_data_root):
    seed_trades(isolated_data_root, "TESTUSDT", {"2026-06-01": [50.0], "2026-06-02": [150.0]})

    fraction = order_size.as_fraction_of_adv(
        20.0, "TESTUSDT", "2026-06-03", days=2, root=isolated_data_root
    )
    back = order_size.quantity_from_adv_fraction(
        fraction, "TESTUSDT", "2026-06-03", days=2, root=isolated_data_root
    )

    assert fraction == pytest.approx(0.2)  # 20 / 100
    assert back == pytest.approx(20.0)


def test_missing_trades_raise_rather_than_yielding_a_zero_denominator(isolated_data_root):
    with pytest.raises(order_size.OrderSizeError, match="no trades partitions"):
        order_size.average_daily_volume("NOSUCHUSDT", "2026-06-04", root=isolated_data_root)


def test_depth_fraction_uses_the_side_the_order_consumes():
    asks = [(100.0, 4.0), (101.0, 6.0), (102.0, 10.0)]

    fraction, present = order_size.as_fraction_of_depth(5.0, asks, depth=2)

    assert fraction == pytest.approx(0.5)  # 5 / (4 + 6)
    assert present == 2


def test_a_thin_book_reports_its_true_level_count():
    """A book thinner than `depth` shrinks the denominator, which reads as a *larger* order.

    Nothing in the fraction itself says the book was thin, so the count comes back alongside it.
    """
    asks = [(100.0, 4.0), (101.0, 6.0)]

    fraction, present = order_size.as_fraction_of_depth(5.0, asks, depth=25)

    assert present == 2
    assert present < 25
    assert fraction == pytest.approx(0.5)


def test_an_empty_side_raises_rather_than_dividing_by_zero():
    with pytest.raises(order_size.OrderSizeError, match="no visible liquidity"):
        order_size.as_fraction_of_depth(1.0, [], depth=25)


def test_sizes_round_down_to_the_committed_step_size():
    """Committed data, never recomputed: a step size that drifted would break reproducibility.

    Rounds *down* so a normalized size never becomes an order larger than the one asked for.
    """
    assert order_size.round_to_step(1234.7, "0GUSDT") == pytest.approx(1234.0)  # step 1
    assert order_size.round_to_step(1.23456, "BTCUSDT") == pytest.approx(1.234)  # step 0.001
    assert order_size.round_to_step(0.0009, "BTCUSDT") == pytest.approx(0.0)


def test_an_unknown_symbol_is_rejected_rather_than_defaulted():
    with pytest.raises(order_size.OrderSizeError, match="not in symbol_meta"):
        order_size.round_to_step(1.0, "NOSUCHUSDT")


@pytest.mark.network
@pytest.mark.parametrize("day", ["2026-06-01", "2026-07-01", "2026-07-15"])
def test_corpus_daily_volume_agrees_with_the_venue_s_own_bar_volume(monkeypatch, day):
    """D-022's cross-check, and the criterion for this task.

    Volume summed from the `trades` corpus against Binance's published daily kline for the same
    symbol-day. These are two independent aggregations of the same underlying trades: ours, and
    the venue's. Agreement is the first evidence in this project that our trades ingest is
    *complete* -- every other check is internal and passes on a corpus that is merely missing rows.

    Reads the real corpus rather than the isolated root, so it is skipped unless the day is on
    disk.

    **Asserted as exact equality, because that turned out to be available.** D-022 declined to
    pick a tolerance in advance -- one chosen before seeing the discrepancy is one chosen to pass
    -- and said to assert exactly if the two agreed. Measured 2026-08-30 on `0GUSDT` 2026-06-01,
    2026-07-01 and 2026-07-15: identical to the last bit, three days spanning a 20x range in
    volume. Same outcome as M2-T2, where the strict criterion was likewise available and better.
    Do not loosen this to an epsilon without recording what differed and why.
    """
    from perpcarry.ingestion import fetch_klines
    from perpcarry.storage import DATA_ROOT_ENV_VAR, data_root

    # The autouse safety net points every test at a tmp root so a synthetic payload can never
    # reach the real corpus. This test has the opposite need -- it must read the real corpus --
    # so it drops the override and lets `data_root()` fall back to its own default, rather than
    # restating where that is (C15). Nothing here writes, so the net has nothing to protect.
    monkeypatch.delenv(DATA_ROOT_ENV_VAR, raising=False)

    symbol = "0GUSDT"
    partition = data_root() / fetch_trades.STORAGE_DIR / f"symbol={symbol}" / f"date={day}"
    if not partition.is_dir():
        pytest.skip(f"no local trades partition for {symbol} {day}")

    ours = float(
        order_size.daily_volumes(
            symbol, start=dt.date.fromisoformat(day), end=dt.date.fromisoformat(day)
        ).iloc[0]
    )
    theirs = float(fetch_klines.fetch_day(symbol, day).iloc[0]["volume"])

    assert ours == theirs, (
        f"corpus volume {ours} vs venue bar volume {theirs}: the trades ingest and the venue "
        f"disagree about how much traded on {day}"
    )
