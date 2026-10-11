"""M1-mark-prices: calendar, decimal, causal availability and archive provenance."""

import hashlib
import io
import zipfile

import httpx
import pandas as pd
import pyarrow.parquet as pq
import pytest

from perpcarry.ingestion import fetch_mark_prices as marks
from perpcarry.ingestion.binance_archive import KLINE_COLUMNS
from perpcarry.ingestion.download import ChecksumMismatch


@pytest.fixture
def raw():
    start, end = marks.month_bounds("2025-02")
    times = list(range(start, end, marks.MINUTE_MS))
    return pd.DataFrame(
        {
            "open_time": times,
            "open": "100.00000001",
            "high": "102",
            "low": "99",
            "close": "101.00000002",
            "volume": "0",
            "close_time": [value + 59999 for value in times],
            "quote_volume": "0",
            "count": "60",
            "taker_buy_volume": "0",
            "taker_buy_quote_volume": "0",
            "ignore": "0",
        },
        columns=KLINE_COLUMNS,
    ).astype(str)


def test_complete_month_preserves_decimal_and_close_availability(raw, tmp_path):
    frame = marks.normalise(raw, "BTCUSDT", "2025-02")
    assert len(frame) == 40320
    assert frame.open.iloc[0] == "100.00000001"
    assert frame.close.iloc[-1] == "101.00000002"
    assert (frame.available_at_ms == frame.open_time + 60000).all()
    paths = marks.store(frame, root=tmp_path)
    assert len(paths) == 28
    assert paths[0].parent == marks.partition_path("BTCUSDT", "2025-02-01", tmp_path)
    table = pq.ParquetFile(paths[0]).read().to_pandas()
    pd.testing.assert_frame_equal(
        table, frame.iloc[:1440].drop(columns=["symbol", "date"]), check_exact=True
    )
    hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
    marks.store(frame, root=tmp_path)
    assert hashes == [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]


def test_exact_header_and_no_header_agree(raw):
    headed = pd.concat([pd.DataFrame([KLINE_COLUMNS], columns=KLINE_COLUMNS), raw])
    pd.testing.assert_frame_equal(
        marks.normalise(raw, "BTCUSDT", "2025-02"),
        marks.normalise(headed, "BTCUSDT", "2025-02"),
        check_exact=True,
    )


@pytest.mark.parametrize(
    "defect",
    [
        "missing",
        "duplicate",
        "unordered",
        "month",
        "close_time",
        "nonfinite",
        "negative",
        "extrema",
        "header",
    ],
)
def test_rejects_structural_defect(raw, defect):
    if defect == "missing":
        raw = raw.iloc[1:]
    elif defect == "duplicate":
        raw.loc[1, "open_time"] = raw.loc[0, "open_time"]
    elif defect == "unordered":
        raw = raw.iloc[::-1]
    elif defect == "month":
        raw.open_time = raw.open_time.astype("int64") + 86400000
    elif defect == "close_time":
        raw.loc[2, "close_time"] = str(int(raw.loc[2, "close_time"]) + 1)
    elif defect == "nonfinite":
        raw.loc[1, "open"] = "NaN"
    elif defect == "negative":
        raw.loc[1, "low"] = "-2"
    elif defect == "extrema":
        raw.loc[1, "high"] = "100"
    else:
        raw.loc[0, "open_time"] = "bad_header"
    with pytest.raises(marks.MarkPriceDataError):
        marks.normalise(raw, "BTCUSDT", "2025-02")


def zip_payload(raw):
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("BTCUSDT-1m-2025-02.csv", raw.to_csv(index=False))
    return payload.getvalue()


def test_checksum_verified_dataset_specific_cache(raw, tmp_path):
    payload = zip_payload(raw)
    digest = hashlib.sha256(payload).hexdigest()
    seen = []

    def respond(request):
        seen.append(str(request.url))
        return (
            httpx.Response(200, text=digest + " filename")
            if str(request.url).endswith(".CHECKSUM")
            else httpx.Response(200, content=payload)
        )

    # Same basename trade cache is poisoned; mark ingestion must never touch it.
    poisoned = tmp_path / ".cache" / "BTCUSDT-1m-2025-02.zip"
    poisoned.parent.mkdir()
    poisoned.write_bytes(b"trade-klines")
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        frame, source = marks.fetch_month("BTCUSDT", "2025-02", root=tmp_path, client=client)
        marks.fetch_month("BTCUSDT", "2025-02", root=tmp_path, client=client)
    assert len(frame) == 40320
    assert source["sha256"] == digest
    assert "/markPriceKlines/BTCUSDT/1m/" in source["url"]
    assert seen.count(source["url"]) == 1
    assert poisoned.read_bytes() == b"trade-klines"


@pytest.mark.parametrize("bad_digest", [None, "broken", "0" * 64])
def test_missing_malformed_or_wrong_checksum_rejected(raw, tmp_path, bad_digest):
    payload = zip_payload(raw)

    def respond(request):
        if str(request.url).endswith(".CHECKSUM"):
            return (
                httpx.Response(404) if bad_digest is None else httpx.Response(200, text=bad_digest)
            )
        return httpx.Response(200, content=payload)

    with (
        httpx.Client(transport=httpx.MockTransport(respond)) as client,
        pytest.raises((marks.MarkPriceDataError, ChecksumMismatch)),
    ):
        marks.fetch_month("BTCUSDT", "2025-02", root=tmp_path, client=client)


@pytest.mark.parametrize("month", ["2025-2", "2025-13", "junk"])
def test_bad_month_rejected(month):
    with pytest.raises(ValueError):
        marks.month_bounds(month)


def test_whole_day_repaired_from_checksummed_daily_archive(raw, tmp_path):
    missing = raw.iloc[1440:2880]
    incomplete = pd.concat([raw.iloc[:1440], raw.iloc[2880:]])
    payload = zip_payload(missing)
    digest = hashlib.sha256(payload).hexdigest()
    seen = []

    def respond(request):
        seen.append(str(request.url))
        return (
            httpx.Response(200, text=digest)
            if str(request.url).endswith(".CHECKSUM")
            else httpx.Response(200, content=payload)
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        repaired, sources = marks.supplement_missing_days(
            incomplete, "BTCUSDT", "2025-02", root=tmp_path, client=client
        )
    assert len(sources) == 1
    assert sources[0]["sha256"] == digest
    assert sources[0]["url"].endswith("BTCUSDT-1m-2025-02-02.zip")
    pd.testing.assert_frame_equal(repaired, raw, check_exact=True)
    assert len(marks.normalise(repaired, "BTCUSDT", "2025-02")) == 40320


def test_daily_repair_rejects_wrong_day(raw, tmp_path):
    incomplete = raw.iloc[1440:]
    payload = zip_payload(raw.iloc[1440:2880])
    digest = hashlib.sha256(payload).hexdigest()

    def respond(request):
        return (
            httpx.Response(200, text=digest)
            if str(request.url).endswith(".CHECKSUM")
            else httpx.Response(200, content=payload)
        )

    with (
        httpx.Client(transport=httpx.MockTransport(respond)) as client,
        pytest.raises(marks.MarkPriceDataError, match="daily minute calendar"),
    ):
        marks.supplement_missing_days(
            incomplete, "BTCUSDT", "2025-02", root=tmp_path, client=client
        )


def test_partial_minute_gap_not_repaired(raw, tmp_path):
    def respond(request):
        pytest.fail("isolated minute gaps must not trigger day repair")

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result, sources = marks.supplement_missing_days(
            raw.iloc[1:], "BTCUSDT", "2025-02", root=tmp_path, client=client
        )
    assert len(result) == 40319
    assert sources == []
    with pytest.raises(marks.MarkPriceDataError, match="missing"):
        marks.normalise(result, "BTCUSDT", "2025-02")
