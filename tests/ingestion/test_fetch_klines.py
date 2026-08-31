"""M4-T3 -- the daily kline downloader, D-022's independent volume reference.

Every fixture is synthetic. Klines are not licence-restricted the way book data is, but the
project's rule is that fixtures are constructed rather than captured, so a test never depends on
what a vendor happened to serve on one day.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from perpcarry.ingestion import binance_archive as archive
from perpcarry.ingestion import fetch_klines


def raw_bars(rows: list[list[str]], *, header: bool = False) -> pd.DataFrame:
    """A frame shaped like the headerless archive CSV, read positionally."""
    body = [archive.KLINE_COLUMNS] + rows if header else rows
    return pd.DataFrame(body, columns=archive.KLINE_COLUMNS, dtype=str)


def bar(open_time: int, *, volume: str = "1000.5", quote: str = "420.25") -> list[str]:
    return [
        str(open_time),
        "0.41",
        "0.44",
        "0.40",
        "0.42",
        volume,
        str(open_time + 86_399_999),
        quote,
        "1234",
        "500.0",
        "210.0",
        "0",
    ]


def test_the_url_carries_the_interval_segment():
    """archive.daily_url would 404 here, and a 404 reads as "the venue has no such day"."""
    url = archive.klines_daily_url("0GUSDT", "2026-06-01", interval=fetch_klines.INTERVAL)

    assert "/klines/0GUSDT/1d/" in url
    assert url.endswith("0GUSDT-1d-2026-06-01.zip")


def test_normalise_maps_positional_columns_onto_the_schema():
    frame = fetch_klines.normalise(raw_bars([bar(1780272000000)]), "0GUSDT")

    assert list(frame.columns) == list(fetch_klines.SCHEMA)
    row = frame.iloc[0]
    # Asserted field by field with distinct values, so a transposition fails rather than
    # cancelling out -- volume and quote_volume are the two that matter and are easy to swap.
    assert row["open_time"] == 1780272000000
    assert row["symbol"] == "0GUSDT"
    assert row["close"] == 0.42
    assert row["volume"] == 1000.5
    assert row["quote_volume"] == 420.25
    assert row["trades"] == 1234
    assert row["date"] == "2026-06-01"


def test_a_header_row_inside_the_csv_is_not_read_as_a_bar():
    """The archive has shipped klines both ways. Guessing wrong turns the header into NaNs."""
    with_header = fetch_klines.normalise(raw_bars([bar(1780272000000)], header=True), "0GUSDT")
    without = fetch_klines.normalise(raw_bars([bar(1780272000000)]), "0GUSDT")

    assert len(with_header) == 1
    assert with_header.iloc[0]["volume"] == without.iloc[0]["volume"]


def test_bars_are_sorted_by_open_time():
    frame = fetch_klines.normalise(raw_bars([bar(1780358400000), bar(1780272000000)]), "0GUSDT")
    assert frame["open_time"].is_monotonic_increasing


def test_a_changed_column_layout_is_rejected_rather_than_misread():
    """Positional columns and no header: a layout change is silent unless it is checked."""
    frame = raw_bars([bar(1780272000000)]).rename(columns={"quote_volume": "something_else"})

    with pytest.raises(fetch_klines.KlineDataError, match="columns changed"):
        fetch_klines.normalise(frame, "0GUSDT")


def test_negative_volume_is_rejected():
    with pytest.raises(fetch_klines.KlineDataError, match="negative"):
        fetch_klines.normalise(raw_bars([bar(1780272000000, volume="-1.0")]), "0GUSDT")


def test_an_empty_file_is_an_error_not_an_empty_frame():
    """An empty frame would flow onward and read as a day with no trading."""
    with pytest.raises(fetch_klines.KlineDataError, match="no bars"):
        fetch_klines.normalise(raw_bars([]), "0GUSDT")


def test_store_and_partition_path_agree(isolated_data_root):
    """Readers locate partitions through the writer, never a restated layout (C15)."""
    frame = fetch_klines.normalise(raw_bars([bar(1780272000000)]), "0GUSDT")
    fetch_klines.store(frame, root=isolated_data_root)

    directory = fetch_klines.partition_path("0GUSDT", dt.date(2026, 6, 1), root=isolated_data_root)
    assert directory.is_dir()
    assert list(directory.glob("*.parquet"))


@pytest.mark.network
def test_a_real_day_downloads_and_normalises():
    frame = fetch_klines.fetch_day("BTCUSDT", "2026-06-01")

    assert len(frame) == 1  # one daily bar
    assert frame.iloc[0]["date"] == "2026-06-01"
    assert frame.iloc[0]["volume"] > 0
    assert frame.iloc[0]["quote_volume"] > 0
