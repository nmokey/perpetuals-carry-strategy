# M0-T6 — Ingestion dependencies

**Milestone:** M0
**Status:** Draft
**Depends on:** M0-T4 (complete)
**Design doc:** Section 4.1, Section 10

## Goal

Give the environment the ability to download and unpack remote archives, and provide the one shared
helper every M1 fetcher needs. Surfaced by the external-dependencies audit: **the project currently
has no HTTP client at all** — `pyproject.toml` lists duckdb, matplotlib, numpy, pandas, polars,
pyarrow, scikit-learn, statsmodels and nothing that can make a request. Every M1 task is blocked on
this, and without it each fetcher would add its own dependency ad hoc.

M0-T1..T5 are complete; this is late-identified M0 scope, not a reopening of finished work.

## Scope

Add an HTTP client dependency and `python/perpcarry/ingestion/download.py` providing:

| Function | Responsibility |
|---|---|
| `fetch(url, dest)` | Streamed download to disk with timeout and bounded retry on transient failures |
| `verify_checksum(path, expected)` | SHA-256 against a sibling `.CHECKSUM`, where the source publishes one |
| `extract_csv(path)` | Read a `.zip`/`.csv.gz` archive into a DataFrame without materialising the whole file where avoidable |
| `cached_fetch(url, cache_dir)` | Skip the download when a verified local copy exists |

Streaming matters: a single order book day is ~449 MB compressed, so nothing may assume the
response fits in memory. `cached_fetch` matters because re-downloading that during development is
slow enough to discourage iteration.

**Dependency choice:** `httpx`. It streams cleanly, has sane timeout defaults, and is
well-maintained. `requests` would also work; the decision is not load-bearing and should be
recorded as a D-entry so it is not re-litigated.

## Acceptance criteria

Proposed for the design doc Section 5 M0 table:

> A checksum-verified archive can be downloaded, extracted, and read into a DataFrame by a test;
> no M1 script needs to add a dependency

| # | Test | Where |
|---|---|---|
| 1 | A gzip/zip fixture served from a local temp file extracts to the expected DataFrame | `tests/ingestion/test_download.py` |
| 2 | Checksum mismatch raises, and **no partial file is left** at the destination | same |
| 3 | A transient failure (first attempt errors, second succeeds) is retried; a permanent one raises with the URL in the message | same |
| 4 | `cached_fetch` performs no second request when a verified copy exists | same |
| 5 | Downloading a real archive works end to end | same, marked `network`, deselected by default |
| 6 | A large file streams rather than buffering — asserted by patching the writer and checking it is called more than once | same |

Test 2 is the one that matters in practice: a truncated download that silently persists is
indistinguishable from a thin trading day, which is exactly the class of defect M1-T4 exists to
catch and would rather not have to.

## Out of scope

- Any dataset-specific logic — that belongs to the M1 fetchers.
- Rate limiting and backoff policy for venue APIs. Both sources are static file hosts and no venue
  API is used (§4.1), so this is genuinely not needed.
- Authentication. Both sources are unauthenticated; the vendor's free tier needs no API key.

## Open questions

**Q1 — where does the download cache live?** Suggest `data/.cache/` so it is already gitignored and
sits beside the data it derives, with `PERPCARRY_DATA_ROOT` continuing to relocate everything.

**Q2 — `httpx` or `requests`?** Recommend `httpx`; record the choice as a D-entry either way.
