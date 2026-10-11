"""M1-T6: synthetic price bars check timestamps, causality, coverage and cache isolation."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from perpcarry.ingestion import binance_archive, fetch_funding, fetch_price_bars

MONTH = dt.date(2025, 7, 1)


def raw(market="futures"):
    start, end = fetch_funding.month_bounds(MONTH)
    divisor = 1000 if market == "spot" else 1
    rows = [
        [
            str(timestamp * divisor),
            "100",
            "104",
            "98",
            "102",
            "30.5",
            str((timestamp + 60000) * divisor - 1),
            "3111",
            "7",
            "15",
            "1500",
            "0",
        ]
        for timestamp in range(start, end, 60000)
    ]
    return pd.DataFrame(rows, columns=binance_archive.KLINE_COLUMNS, dtype=str)


def test_spot_microseconds_and_futures_milliseconds_normalize_identically():
    futures = fetch_price_bars.normalise(raw(), "TESTUSDT", MONTH, "futures")
    spot = fetch_price_bars.normalise(raw("spot"), "TESTUSDT", MONTH, "spot")
    for name in ("open_time", "close_time", "available_at", "close", "volume"):
        pd.testing.assert_series_equal(futures[name], spot[name], check_exact=True)
    assert (futures["available_at"] == futures["open_time"] + 60000).all()
    assert not (futures["available_at"] <= futures["open_time"]).any()


@pytest.mark.parametrize("defect", ["missing", "duplicate", "order", "units", "close"])
def test_bad_minute_coverage_or_units_fail(defect):
    frame = raw()
    if defect == "missing":
        frame = frame.drop(300)
    elif defect == "duplicate":
        frame.loc[300, "open_time"] = frame.loc[299, "open_time"]
    elif defect == "order":
        frame = frame.iloc[::-1]
    elif defect == "units":
        frame["open_time"] = (frame["open_time"].astype("int64") * 1000).astype(str)
    else:
        frame.loc[300, "close_time"] = frame.loc[300, "open_time"]
    with pytest.raises(fetch_price_bars.PriceDataError):
        fetch_price_bars.normalise(frame, "TESTUSDT", MONTH, "futures")


@pytest.mark.parametrize(
    "field,value", [("close", "NaN"), ("open", "0"), ("volume", "-1"), ("high", "99")]
)
def test_bad_prices_and_volumes_fail(field, value):
    frame = raw()
    frame.loc[300, field] = value
    with pytest.raises(fetch_price_bars.PriceDataError):
        fetch_price_bars.normalise(frame, "TESTUSDT", MONTH, "futures")


def test_markets_cannot_share_a_source_url():
    future = fetch_price_bars.archive_url("TESTUSDT", MONTH, "futures")
    spot = fetch_price_bars.archive_url("TESTUSDT", MONTH, "spot")
    assert "/futures/um/" in future
    assert "/spot/" in spot
    assert future != spot


def test_download_caches_and_storage_are_separate_by_market(isolated_data_root, monkeypatch):
    from perpcarry.ingestion.download import sha256

    paths = []
    checksums = []
    monkeypatch.setattr(fetch_price_bars, "fetch_checksum", lambda *args, **kwargs: "verified")

    def fetch(url, *, dest, expected_sha256, **kwargs):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(url)
        paths.append(dest)
        checksums.append(expected_sha256)
        return dest

    monkeypatch.setattr(fetch_price_bars, "cached_fetch", fetch)
    monkeypatch.setattr(
        fetch_price_bars,
        "extract_csv",
        lambda path, **kwargs: raw("spot" if path.parent.name == "spot" else "futures"),
    )
    for market in ("futures", "spot"):
        report = fetch_price_bars.fetch_month("TESTUSDT", MONTH, market)
        assert report["rows"] == 31 * 1440
        file = next(fetch_price_bars.partition_path("TESTUSDT", MONTH, market).glob("*.parquet"))
        assert report["partition_sha256"][str(file.relative_to(isolated_data_root))] == sha256(file)
    assert paths[0] != paths[1]
    assert checksums == ["verified", "verified"]


def test_unpublished_checksum_refuses_download(monkeypatch):
    monkeypatch.setattr(fetch_price_bars, "fetch_checksum", lambda *args, **kwargs: None)

    def forbidden_download(*args, **kwargs):
        pytest.fail("unverified price archive was downloaded")

    monkeypatch.setattr(fetch_price_bars, "cached_fetch", forbidden_download)
    with pytest.raises(fetch_price_bars.PriceDataError, match="no published checksum"):
        fetch_price_bars.fetch_month("TESTUSDT", MONTH, "futures")
