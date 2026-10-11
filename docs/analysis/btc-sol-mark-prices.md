# BTC/SOL mark-price acquisition and remaining settlement evidence

2026-10-10. This task acquired mark-price bars without choosing a settlement proxy.

The [official Binance archive downloader](https://github.com/binance/binance-public-data/blob/master/python/download-futures-markPriceKlines.py)
constructs separate `markPriceKlines` daily/monthly archives. The
[mark-price kline documentation](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Mark-Price-Kline-Candlestick-Data)
describes time-indexed OHLC bars. These bars differ from the previously acquired trade
klines and carry no usable trade volume.

## Acquired coverage

Both BTCUSDT and SOLUSDT now have the full July 1, 2025–September 30, 2026 minute
calendar: 457 days and 658,080 rows each, 1,316,160 rows combined. Thirty monthly
archives and two supplemental daily archives total 28,824,162 compressed bytes;
914 deterministic day Parquet files total 48,336,098 bytes. This is approximately
74 MiB combined, far smaller than book data. Each download was checked against its
published SHA-256, and every month passed exact UTC calendar, endpoint, close-time,
positive-decimal and OHLC-extrema checks.

Both June 2026 monthly files omit June 29 (41,760 versus 43,200 expected rows).
The code caught the omission. Checksum-verified June 29 daily archives supplied those
rows; the merged months then passed the same complete calendar checks. This is a
recorded repair from an independent archive granularity, not forward filling.

Local evidence: `data/btc-sol/reports/mark-prices-status.json` records all original
monthly and supplemental daily URLs, source SHA-256 values, row counts, endpoints,
archive sizes and all generated file hashes. Output is under `data/btc-sol/mark_prices_1m`.
The cache is isolated at `.cache/markPriceKlines`, because trade and mark archives have
identical filenames. The July BTC monthly archive hash is
`33eaa2e5fe002aacdd2656af3457186965325fde98a014d2cef754eb3ce849ad`.

## Availability and remaining limits

OHLC prices retain their source decimal strings. A completed minute bar becomes
available at `close_time + 1 ms`. Its high, low and close must never be available to a
decision at the bar's open timestamp. Publication latency is not measured by these
archives. The `open` is retained separately; no runtime adapter currently substitutes
it for an exact funding mark. Using a previous closed bar for valuation involves an
explicit staleness assumption, particularly for the existing 16-second decision delay.
The terminal bar closes at September 30 23:59:59.999 and is complete at October 1 00:00;
an adapter must handle that valuation boundary explicitly without exposing future
close values to earlier decisions.

Exact funding settlement marks remain missing. The
[official funding-history API](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History)
includes `markPrice` associated with each funding charge. Venue API access is blocked
from this host, and no blocked endpoint was called. A mark bar opening at a funding
boundary is a candidate proxy; the archive does not establish equality with the exact
mark used for funding. Getting authorized funding-history exports from an accessible
host would address that evidence gap. Alternatively, a separately chosen approximation
could bound payments using nearby bar extrema and report sensitivity; this acquisition
does not approve such a change or claim the precise-payment study is ready.

## Reproduce

```bash
uv run python -m perpcarry.ingestion.fetch_mark_prices --root data/btc-sol
uv run pytest -q tests/ingestion/test_fetch_mark_prices.py
```

The fetcher streams HTTP downloads, processes one small month at a time and requires
checksums. It rejects partial-minute gaps and malformed/duplicate/out-of-order calendars;
only entirely omitted UTC days can invoke the explicit daily-archive reconciliation.
Its 21 offline tests passed during implementation, including genuine-source repair
mechanics, cache isolation, precise decimal persistence and causal bar availability.
Eight isolated implementation faults were caught by named test failures: removing
calendar ordering, close-time validation, closed-bar availability, positive prices,
OHLC extrema, checksum verification, cache isolation and supplemental daily calendar
validation. The initial duplicate-row mutation remained caught by the independent
close-time guard; the ordering fixture isolated the calendar guard itself. No collection
error was counted as a detection. Ruff and whitespace checks passed.
