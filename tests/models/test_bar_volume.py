"""Synthetic bar archives exercise exact volume, provenance and causal selection."""

import copy
import datetime as dt
import hashlib
import json
import zipfile
from dataclasses import replace
from decimal import Decimal, localcontext

import pytest

from perpcarry.ingestion import fetch_price_bars
from perpcarry.models import bar_volume
from perpcarry.models import calibration_dataset as calibration

MONTH = dt.date(2025, 6, 1)
SYMBOL = "TESTUSDT"


@pytest.fixture
def archive(tmp_path):
    opened = int(dt.datetime.combine(MONTH, dt.time(), dt.UTC).timestamp()) * 1000
    lines = []
    for offset in range(30 * 1440):
        stamp = opened + offset * 60000
        lines.append(
            f"{stamp},10,11,9,10,0.100000000000000000001,{stamp + 59999},"
            "1.00000000000000000001,1,0,0,0\n"
        )
    url = fetch_price_bars.archive_url(SYMBOL, MONTH, "futures")
    path = tmp_path / ".cache" / fetch_price_bars.STORAGE_DIR / "futures" / url.rsplit("/", 1)[-1]
    path.parent.mkdir(parents=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as handle:
        handle.writestr("bars.csv", "".join(lines))
    report_path = tmp_path / "reports" / f"prices-futures-{SYMBOL}-2025-06.json"
    report_path.parent.mkdir()
    report = {
        "symbol": SYMBOL,
        "month": "2025-06",
        "market": "futures",
        "source": url,
        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    report_path.write_text(json.dumps(report))
    return tmp_path, path, report_path


def test_exact_source_text_not_float_volume(archive):
    root, _, _ = archive
    days = bar_volume.monthly_volumes(root, SYMBOL, MONTH)
    assert len(days) == 30
    assert days[0]["base_volume"] == "144.000000000000000001440"
    assert days[-1]["quote_volume"] == "1440.00000000000000001440"
    assert days[0]["trades"] == 1440
    assert days[0]["minutes"] == 1440


@pytest.mark.parametrize(
    "field,value",
    [
        ("symbol", "OTHER"),
        ("market", "spot"),
        ("month", "2025-07"),
        ("source", "https://invalid.example/archive"),
    ],
)
def test_report_identity_bound_to_source(archive, field, value):
    root, _, report_path = archive
    report = json.loads(report_path.read_text())
    report[field] = value
    report_path.write_text(json.dumps(report))
    with pytest.raises(bar_volume.BarVolumeError, match="identity"):
        bar_volume.monthly_volumes(root, SYMBOL, MONTH)


def test_cached_bytes_checked_against_published_digest(archive):
    root, path, _ = archive
    with path.open("ab") as handle:
        handle.write(b"modified")
    with pytest.raises(bar_volume.BarVolumeError, match="checksum"):
        bar_volume.monthly_volumes(root, SYMBOL, MONTH)


def test_missing_minute_rejected_even_with_updated_digest(archive):
    root, path, report_path = archive
    with zipfile.ZipFile(path) as handle:
        lines = handle.read("bars.csv").decode().splitlines(True)
    with zipfile.ZipFile(path, "w") as handle:
        handle.writestr("bars.csv", "".join(lines[1:]))
    report = json.loads(report_path.read_text())
    report["source_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    report_path.write_text(json.dumps(report))
    with pytest.raises(fetch_price_bars.PriceDataError, match="minutes"):
        bar_volume.monthly_volumes(root, SYMBOL, MONTH)


def artifact():
    return {
        "symbol": SYMBOL,
        "market": "futures",
        "method": bar_volume.METHOD,
        "days": [
            {
                "date": (MONTH + dt.timedelta(days=i)).isoformat(),
                "base_volume": str(i + 1),
                "source_sha256": "a" * 64,
            }
            for i in range(31)
        ],
    }


def test_completed_days_and_decimal_context():
    with localcontext() as context:
        context.prec = 3
        feature = bar_volume.average_daily_volume(artifact(), dt.date(2025, 7, 1))
    assert feature["base_adv"] == "15.5"
    assert feature["adv_start_ms"] == 1748736000000
    assert feature["adv_end_exclusive_ms"] == 1751328000000
    assert feature["method"] == bar_volume.METHOD


def test_adv_precision_independent_of_callers_decimal_context():
    data = artifact()
    for row in data["days"]:
        row["base_volume"] = "0.100000000000000000001"
    with localcontext() as context:
        context.prec = 3
        result = bar_volume.average_daily_volume(data, dt.date(2025, 7, 1))
    assert result["base_adv"] == "0.100000000000000000001"


def test_future_poison_withholding_and_order_do_not_change_feature():
    original = artifact()
    before = bar_volume.average_daily_volume(original, dt.date(2025, 7, 1))
    poisoned = copy.deepcopy(original)
    for row in poisoned["days"]:
        row["source_sha256"] = "b" * 64
        row["report_sha256"] = "c" * 64
    poisoned["days"][-1]["base_volume"] = "NaN"
    poisoned["days"].append({"date": "2025-08-01", "base_volume": object()})
    assert bar_volume.average_daily_volume(poisoned, dt.date(2025, 7, 1)) == before
    poisoned["days"] = poisoned["days"][:30]
    assert bar_volume.average_daily_volume(poisoned, dt.date(2025, 7, 1)) == before


@pytest.mark.parametrize(
    "change", ["missing", "duplicate", "order", "negative", "nonfinite", "method", "market"]
)
def test_bad_prior_window_rejected(change):
    data = artifact()
    if change == "missing":
        data["days"].pop(10)
    elif change == "duplicate":
        data["days"].insert(10, data["days"][10])
    elif change == "order":
        data["days"][9:11] = reversed(data["days"][9:11])
    elif change in {"negative", "nonfinite"}:
        data["days"][10]["base_volume"] = "-1" if change == "negative" else "NaN"
    else:
        data[change] = "wrong"
    with pytest.raises(bar_volume.BarVolumeError):
        bar_volume.average_daily_volume(data, dt.date(2025, 7, 1))


def test_verified_adapter_uses_cached_sources(archive):
    root, _, _ = archive
    result = bar_volume.verified_average_daily_volume(root, SYMBOL, dt.date(2025, 7, 1))
    assert Decimal(result["base_adv"]) == Decimal("144.000000000000000001440")


def test_calibration_raw_trade_default_retained():
    assert calibration.Config().adv_source == "trades"
    with pytest.raises(ValueError):
        calibration.Config(adv_source="futures_bars", adv_days=29)
    with pytest.raises(ValueError):
        calibration.Config(adv_source="unexpected")
    assert replace(calibration.Config(), adv_source="futures_bars").adv_days == 30
