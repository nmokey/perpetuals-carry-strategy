# M0-T6 — Ingestion dependencies

**Milestone:** M0
**Status:** **Complete** (2026-08-12)
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
| 6 | A large file streams rather than buffering | same |

Test 2 is the one that matters in practice: a truncated download that silently persists is
indistinguishable from a thin trading day, which is exactly the class of defect M1-T4 exists to
catch and would rather not have to.

## As built

Delivered as `python/perpcarry/ingestion/download.py` with 18 tests (17 offline + 1 `network`).

Two implementation notes worth carrying forward:

- **Streaming is asserted via an `on_chunk` callback** rather than by patching the writer. The
  callback is genuinely useful (progress reporting on ~449 MB files) and makes the test a
  behavioural assertion instead of a mock-shaped one.
- **A status-only failure does not exercise the partial-file path.** The original test used a
  500, which raises *before* any bytes are written, so no `.part` file ever existed — it passed
  even with the cleanup deleted. Mutation testing caught this; the test now streams real bytes and
  then fails mid-transfer. See convention C12: the first version of that test was decorative.

**Verified by mutation, 6/6 defects detected**, each by exactly one precisely-named test: partial
file left after mid-stream failure, 4xx retried, checksum compared case-sensitively, cache trusted
without re-verifying, body buffered whole, bad download kept after failed verification.

## Out of scope

- Any dataset-specific logic — that belongs to the M1 fetchers.
- Rate limiting and backoff policy for venue APIs. Both sources are static file hosts and no venue
  API is used (§4.1), so this is genuinely not needed.
- Authentication. Both sources are unauthenticated; the vendor's free tier needs no API key.

## Open questions

**Q1 — RESOLVED.** Cache lives at `data/.cache/` via `download.cache_dir()`, already gitignored and
relocatable through `PERPCARRY_DATA_ROOT`.

**Q2 — RESOLVED.** `httpx`, recorded as D-011.

**Q3 — new, deferred.** The Tardis free tier publishes **no** `.CHECKSUM` files (verified: 404), so
book downloads cannot be integrity-checked the way archive downloads can. `fetch_checksum` returns
`None` there rather than failing. M1-T3 will need a different integrity signal — gzip decompression
succeeding end-to-end is the obvious candidate, since a truncated `.gz` fails to inflate.
