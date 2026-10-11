"""Exact, provenance-bound futures-bar ADV alternative; raw-trade defaults are unchanged."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path

from perpcarry.ingestion import binance_archive, fetch_price_bars
from perpcarry.ingestion.download import extract_csv
from perpcarry.integrity import sha256

METHOD = "binance-usdm-1m-base-volume-decimal-prior-30-utc-days-v1"


class BarVolumeError(ValueError):
    """Bar volume or its admission evidence is unusable."""


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def monthly_volumes(root: Path, symbol: str, month: dt.date) -> list[dict]:
    """Validate a cached raw monthly archive and return exact daily aggregates."""
    if month.day != 1:
        raise BarVolumeError("month must start on its first day")
    url = fetch_price_bars.archive_url(symbol, month, "futures")
    report_path = root / "reports" / f"prices-futures-{symbol}-{month:%Y-%m}.json"
    report_bytes = report_path.read_bytes()
    report = json.loads(report_bytes)
    expected = {
        "symbol": symbol,
        "month": month.strftime("%Y-%m"),
        "market": "futures",
        "source": url,
    }
    if any(report.get(key) != value for key, value in expected.items()):
        raise BarVolumeError("price source report identity does not match requested month")
    archive = root / ".cache" / fetch_price_bars.STORAGE_DIR / "futures" / url.rsplit("/", 1)[-1]
    digest = sha256(archive)
    if digest != report.get("source_sha256"):
        raise BarVolumeError("cached price archive differs from its recorded published checksum")
    raw = extract_csv(archive, header=None, names=binance_archive.KLINE_COLUMNS, dtype=str)
    fetch_price_bars.normalise(raw, symbol, month, "futures")
    raw = raw[raw["open_time"] != "open_time"]
    totals: dict[str, dict] = {}
    with localcontext() as context:
        context.prec = 60
        for opened, volume, quote, count in raw[
            ["open_time", "volume", "quote_volume", "count"]
        ].itertuples(index=False, name=None):
            day = dt.datetime.fromtimestamp(int(opened) // 1000, dt.UTC).date().isoformat()
            values = []
            for value in (volume, quote):
                try:
                    number = Decimal(value)
                except InvalidOperation as exc:
                    raise BarVolumeError("invalid decimal volume") from exc
                if not number.is_finite() or number < 0:
                    raise BarVolumeError("nonfinite or negative volume")
                values.append(number)
            item = totals.setdefault(
                day,
                {"base_volume": Decimal(0), "quote_volume": Decimal(0), "trades": 0, "minutes": 0},
            )
            item["base_volume"] += values[0]
            item["quote_volume"] += values[1]
            item["trades"] += int(count)
            item["minutes"] += 1
        result = []
        for day, item in totals.items():
            if item["minutes"] != 1440 or item["base_volume"] <= 0:
                raise BarVolumeError("incomplete or nonpositive daily volume")
            result.append(
                {
                    "date": day,
                    **{
                        key: format(value, "f") if isinstance(value, Decimal) else value
                        for key, value in item.items()
                    },
                    "source": url,
                    "source_sha256": digest,
                    "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
                }
            )
    if sha256(archive) != digest or report_path.read_bytes() != report_bytes:
        raise BarVolumeError("source changed during volume admission")
    return result


def average_daily_volume(artifact: dict, as_of: dt.date) -> dict:
    """A deterministic, explicitly labeled 30-completed-day feature and evidence hash."""
    if artifact.get("method") != METHOD or artifact.get("market") != "futures":
        raise BarVolumeError("unsupported ADV method or market")
    start = as_of - dt.timedelta(days=30)
    selected = [
        row for row in artifact["days"] if start.isoformat() <= row["date"] < as_of.isoformat()
    ]
    expected = [(start + dt.timedelta(days=offset)).isoformat() for offset in range(30)]
    if [row["date"] for row in selected] != expected:
        raise BarVolumeError("ADV requires exactly 30 ordered completed UTC days")
    with localcontext() as context:
        context.prec = 60
        quantities = [Decimal(row["base_volume"]) for row in selected]
        if any(not value.is_finite() or value <= 0 for value in quantities):
            raise BarVolumeError("invalid prior daily volume")
        value = sum(quantities, Decimal(0)) / Decimal(30)
    evidence = {
        "method": METHOD,
        "symbol": artifact["symbol"],
        "market": "futures",
        "start": start.isoformat(),
        "end_exclusive": as_of.isoformat(),
        # Monthly hashes can change when a future row is poisoned. Keep those in
        # offline admission provenance, outside this strictly prior feature digest.
        "days": [
            {key: row[key] for key in ("date", "base_volume", "source") if key in row}
            for row in selected
        ],
    }
    return {
        "base_adv": format(value, "f"),
        "method": METHOD,
        "symbol": artifact["symbol"],
        "adv_start_ms": int(dt.datetime.combine(start, dt.time(), dt.UTC).timestamp()) * 1000,
        "adv_end_exclusive_ms": int(dt.datetime.combine(as_of, dt.time(), dt.UTC).timestamp())
        * 1000,
        "evidence_sha256": _digest(evidence),
    }


def verified_volume_inputs(root: Path, symbol: str, as_of: dt.date) -> dict:
    """Revalidate selected raw months before constructing a feature; no artifact trust."""
    start = as_of - dt.timedelta(days=30)
    months = sorted({(start + dt.timedelta(days=offset)).replace(day=1) for offset in range(30)})
    artifact = {
        "method": METHOD,
        "market": "futures",
        "symbol": symbol,
        "days": [row for month in months for row in monthly_volumes(root, symbol, month)],
    }
    provenance = [
        {key: row[key] for key in ("source", "source_sha256", "report_sha256")}
        for row in artifact["days"]
        if row["date"].endswith("-01")
    ]
    return {"adv": average_daily_volume(artifact, as_of), "archive_provenance": provenance}


def verified_average_daily_volume(root: Path, symbol: str, as_of: dt.date) -> dict:
    """Expose only the causal feature; full-file evidence is separately available."""
    return verified_volume_inputs(root, symbol, as_of)["adv"]
