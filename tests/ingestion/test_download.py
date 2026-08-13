"""M0-T6 acceptance: download, verify, extract -- without leaving partial files behind."""

import gzip
import hashlib
import zipfile

import httpx
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from perpcarry.ingestion.download import (
    ChecksumMismatch,
    DownloadError,
    cached_fetch,
    extract_csv,
    fetch,
    fetch_checksum,
    parse_checksum,
    sha256,
    verify_checksum,
)

BODY = b"col_a,col_b\n1,x\n2,y\n"
EXPECTED = pd.DataFrame({"col_a": [1, 2], "col_b": ["x", "y"]})


def client_for(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def always(status: int, content: bytes = BODY):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=content)

    return handler


def counting(status: int = 200, content: bytes = BODY):
    """Handler that records how many requests it served."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(status, content=content)

    return handler, calls


# --- fetch -------------------------------------------------------------------


def test_fetch_writes_file(tmp_path):
    dest = tmp_path / "out.csv"

    with client_for(always(200)) as client:
        fetch("https://example.test/x.csv", dest, client=client)

    assert dest.read_bytes() == BODY


def test_transient_failure_is_retried(tmp_path):
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(200, content=BODY)

    with client_for(handler) as client:
        fetch("https://example.test/x.csv", tmp_path / "out.csv", client=client, backoff=0)

    assert attempts["n"] == 2


def test_retryable_status_is_retried_then_gives_up(tmp_path):
    handler, calls = counting(503)

    with client_for(handler) as client, pytest.raises(DownloadError, match="after 3 attempts"):
        fetch("https://example.test/x.csv", tmp_path / "out.csv", client=client, backoff=0)

    assert len(calls) == 3


def test_permanent_failure_raises_immediately_and_names_the_url(tmp_path):
    handler, calls = counting(401)
    url = "https://datasets.example.test/2026/06/02/BTCUSDT.csv.gz"

    with client_for(handler) as client, pytest.raises(DownloadError, match="401.*BTCUSDT"):
        fetch(url, tmp_path / "out.gz", client=client, backoff=0)

    assert len(calls) == 1, "4xx must not be retried"


def test_no_file_written_when_the_response_fails_before_any_bytes(tmp_path):
    target = tmp_path / "downloads"
    dest = target / "out.csv"

    with client_for(always(500)) as client, pytest.raises(DownloadError):
        fetch("https://example.test/x.csv", dest, client=client, backoff=0)

    assert not dest.exists()
    assert list(target.iterdir()) == []


def test_no_partial_file_survives_a_mid_stream_failure(tmp_path):
    """The case that actually matters: bytes land on disk, then the transfer dies.

    A truncated archive left behind is indistinguishable from a thin trading day, so it
    must not survive. Note a status-only failure does *not* exercise this path -- nothing
    is written before the status check -- which is why this test streams real bytes first.
    """
    target = tmp_path / "downloads"
    dest = target / "out.csv"

    def handler(request: httpx.Request) -> httpx.Response:
        def body():
            yield b"first-half-of-the-archive"
            raise httpx.ReadError("connection dropped mid-stream", request=request)

        return httpx.Response(200, content=body())

    with client_for(handler) as client, pytest.raises(DownloadError):
        fetch("https://example.test/x.csv", dest, client=client, backoff=0, chunk_size=8)

    assert not dest.exists()
    assert list(target.iterdir()) == [], "a truncated .part file was left behind"


def test_download_streams_rather_than_buffering(tmp_path):
    """Chunk callback fires more than once, so the body is not materialised whole."""
    big = b"x" * (5 * 1024)
    sizes: list[int] = []

    with client_for(always(200, big)) as client:
        fetch(
            "https://example.test/big",
            tmp_path / "big.bin",
            client=client,
            chunk_size=1024,
            on_chunk=sizes.append,
        )

    assert len(sizes) > 1
    assert sum(sizes) == len(big)


# --- checksums ---------------------------------------------------------------


def test_parse_checksum_handles_the_published_format():
    digest = "cff97ce688329592bccbbf5873b5c7021649e093f5f5806e332c5b4fb7fd6a00"

    assert parse_checksum(f"{digest}  BTCUSDT-fundingRate-2026-06.zip\n") == digest


def test_verify_checksum_accepts_and_rejects(tmp_path):
    path = tmp_path / "f.bin"
    path.write_bytes(BODY)

    verify_checksum(path, sha256(path).upper())  # case-insensitive

    with pytest.raises(ChecksumMismatch, match="expected"):
        verify_checksum(path, "0" * 64)


def test_missing_checksum_is_not_an_error(tmp_path):
    """The vendor publishes no .CHECKSUM files; that must not fail the fetch."""
    with client_for(always(404, b"")) as client:
        assert fetch_checksum("https://datasets.example.test/x.csv.gz", client=client) is None


# --- caching -----------------------------------------------------------------


def test_default_cache_lives_under_the_data_root(isolated_data_root):
    """The isolation the conftest fixture relies on -- asserted, not assumed.

    If ``cache_dir()`` ever stops deriving from the data root, tests would silently start
    writing into the project's real ``data/.cache/`` again.
    """
    from perpcarry.ingestion.download import cache_dir

    assert cache_dir() == isolated_data_root / ".cache"


def test_cached_fetch_without_dest_stays_inside_the_data_root(isolated_data_root):
    handler, calls = counting()

    with client_for(handler) as client:
        path = cached_fetch("https://example.test/archive.zip", client=client)

    assert path.is_relative_to(isolated_data_root)


def test_cached_fetch_skips_the_request_when_a_copy_exists(tmp_path):
    dest = tmp_path / "x.csv"
    handler, calls = counting()

    with client_for(handler) as client:
        cached_fetch("https://example.test/x.csv", dest=dest, client=client)
        cached_fetch("https://example.test/x.csv", dest=dest, client=client)

    assert len(calls) == 1


def test_cached_fetch_reverifies_and_replaces_a_corrupt_entry(tmp_path):
    dest = tmp_path / "x.csv"
    dest.write_bytes(b"corrupted")
    digest = hashlib.sha256(BODY).hexdigest()
    handler, calls = counting()

    with client_for(handler) as client:
        path = cached_fetch(
            "https://example.test/x.csv", dest=dest, expected_sha256=digest, client=client
        )

    assert path.read_bytes() == BODY
    assert len(calls) == 1, "corrupt cache entry should trigger exactly one re-fetch"


def test_cached_fetch_removes_a_download_that_fails_verification(tmp_path):
    dest = tmp_path / "x.csv"

    with client_for(always(200)) as client, pytest.raises(ChecksumMismatch):
        cached_fetch(
            "https://example.test/x.csv", dest=dest, expected_sha256="0" * 64, client=client
        )

    assert not dest.exists()


# --- extraction --------------------------------------------------------------


def test_extract_zip(tmp_path):
    path = tmp_path / "a.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("a.csv", BODY.decode())

    assert_frame_equal(extract_csv(path), EXPECTED)


def test_extract_gzip(tmp_path):
    path = tmp_path / "a.csv.gz"
    path.write_bytes(gzip.compress(BODY))

    assert_frame_equal(extract_csv(path), EXPECTED)


def test_extract_plain_csv(tmp_path):
    path = tmp_path / "a.csv"
    path.write_bytes(BODY)

    assert_frame_equal(extract_csv(path), EXPECTED)


def test_ambiguous_zip_is_rejected(tmp_path):
    path = tmp_path / "a.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("a.csv", BODY.decode())
        archive.writestr("b.csv", BODY.decode())

    with pytest.raises(DownloadError, match="exactly one CSV"):
        extract_csv(path)


def test_extract_passes_read_csv_kwargs(tmp_path):
    path = tmp_path / "a.csv"
    path.write_bytes(b"1,x\n2,y\n")

    result = extract_csv(path, names=["col_a", "col_b"])

    assert_frame_equal(result, EXPECTED)


# --- end to end against the real archive -------------------------------------


@pytest.mark.network
def test_real_archive_round_trip(tmp_path):
    """Download a real archive, verify its published checksum, and read it."""
    url = (
        "https://data.binance.vision/data/futures/um/monthly/fundingRate/"
        "BTCUSDT/BTCUSDT-fundingRate-2026-06.zip"
    )
    digest = fetch_checksum(url)
    assert digest is not None, "the Binance archive publishes checksums"

    path = cached_fetch(url, dest=tmp_path / "f.zip", expected_sha256=digest)
    frame = extract_csv(path)

    assert list(frame.columns) == ["calc_time", "funding_interval_hours", "last_funding_rate"]
    assert len(frame) == 90  # 30 days x 3 settlements at 8h
