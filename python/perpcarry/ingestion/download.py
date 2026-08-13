"""Download and extraction helpers for the ingestion layer (design-doc M0-T6).

Both data sources are static file hosts over HTTPS -- the Binance S3 archive and the
Tardis.dev free tier -- so this module deliberately handles no authentication, no rate
limiting, and no venue API semantics. See design doc Section 4.1.

Two properties matter more than they might look:

* **Streaming.** A single order book day is ~449 MB compressed, so nothing here may
  assume a response fits in memory.
* **No partial files.** Downloads land on a ``.part`` file and are renamed into place only
  on success. A truncated archive that persists is indistinguishable from a thin trading
  day, which is exactly the defect class M1-T4 exists to catch.
"""

from __future__ import annotations

import gzip
import hashlib
import time
import zipfile
from collections.abc import Callable
from pathlib import Path

import httpx
import pandas as pd

from perpcarry.storage import data_root

CHUNK_SIZE = 1 << 20  # 1 MiB
DEFAULT_TIMEOUT = 30.0
DEFAULT_RETRIES = 3
DEFAULT_BACKOFF = 0.5

# Transient by nature: worth retrying rather than failing the whole backfill.
RETRY_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


class DownloadError(RuntimeError):
    """A download failed in a way the caller must handle."""


class ChecksumMismatch(DownloadError):
    """Downloaded bytes did not match the published checksum."""


class _Transient(DownloadError):
    """Internal: a failure worth retrying."""


def cache_dir() -> Path:
    """Directory for downloaded archives.

    Lives under the data root so it is already gitignored and relocatable via
    ``PERPCARRY_DATA_ROOT``.
    """
    return data_root() / ".cache"


def fetch(
    url: str,
    dest: str | Path,
    *,
    client: httpx.Client | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    chunk_size: int = CHUNK_SIZE,
    backoff: float = DEFAULT_BACKOFF,
    on_chunk: Callable[[int], None] | None = None,
) -> Path:
    """Stream ``url`` to ``dest``, retrying transient failures.

    ``on_chunk`` is called with each chunk's size as it is written -- useful for progress
    reporting on multi-hundred-megabyte files, and the hook the streaming test asserts on.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")

    owns_client = client is None
    client = client or httpx.Client(timeout=timeout, follow_redirects=True)
    try:
        last_error: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                _stream_to(client, url, part, chunk_size, on_chunk)
            except (httpx.TransportError, _Transient) as exc:
                # A mid-stream failure leaves bytes on disk; drop them so the next
                # attempt cannot append to a truncated file.
                last_error = exc
                part.unlink(missing_ok=True)
                if attempt < retries:
                    time.sleep(backoff * attempt)
                continue
            except BaseException:
                part.unlink(missing_ok=True)
                raise
            part.replace(dest)
            return dest

        raise DownloadError(
            f"failed to fetch {url} after {retries} attempts: {last_error}"
        ) from last_error
    finally:
        if owns_client:
            client.close()


def _stream_to(
    client: httpx.Client,
    url: str,
    part: Path,
    chunk_size: int,
    on_chunk: Callable[[int], None] | None,
) -> None:
    with client.stream("GET", url) as response:
        if response.status_code in RETRY_STATUS:
            raise _Transient(f"HTTP {response.status_code} fetching {url}")
        if response.status_code >= 400:
            # Permanent: a 401 here means a Tardis non-first-of-month date, a 404 a
            # missing archive day. Both are caller errors, not worth retrying.
            raise DownloadError(f"HTTP {response.status_code} fetching {url}")

        with part.open("wb") as handle:
            for chunk in response.iter_bytes(chunk_size):
                handle.write(chunk)
                if on_chunk is not None:
                    on_chunk(len(chunk))


def sha256(path: str | Path, chunk_size: int = CHUNK_SIZE) -> str:
    """SHA-256 of a file, read in chunks so large archives stay out of memory."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def parse_checksum(text: str) -> str:
    """Extract the digest from a published checksum file.

    Binance publishes ``<sha256>  <filename>``. Returns the digest alone.
    """
    parts = text.split()
    if not parts:
        raise ValueError("empty checksum file")
    return parts[0].lower()


def verify_checksum(path: str | Path, expected: str) -> None:
    """Raise :class:`ChecksumMismatch` unless ``path`` hashes to ``expected``."""
    actual = sha256(path)
    if actual != expected.lower():
        raise ChecksumMismatch(f"{Path(path).name}: expected {expected.lower()}, got {actual}")


def fetch_checksum(url: str, *, client: httpx.Client | None = None) -> str | None:
    """Fetch the digest from ``<url>.CHECKSUM``, or ``None`` where none is published.

    The Binance archive publishes one per file; the Tardis free tier does not (404), so a
    missing checksum is an expected outcome rather than an error.
    """
    owns_client = client is None
    client = client or httpx.Client(timeout=DEFAULT_TIMEOUT, follow_redirects=True)
    try:
        response = client.get(f"{url}.CHECKSUM")
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise DownloadError(f"HTTP {response.status_code} fetching {url}.CHECKSUM")
        return parse_checksum(response.text)
    finally:
        if owns_client:
            client.close()


def cached_fetch(
    url: str,
    *,
    dest: str | Path | None = None,
    expected_sha256: str | None = None,
    client: httpx.Client | None = None,
    **fetch_kwargs,
) -> Path:
    """Fetch ``url`` unless a valid local copy already exists.

    With ``expected_sha256`` the cached copy is verified before being trusted; without it,
    presence is taken as sufficient. Re-downloading a 449 MB book day on every run makes
    iteration painful enough that people start commenting out the download.
    """
    path = Path(dest) if dest is not None else cache_dir() / url.rsplit("/", 1)[-1]

    if path.exists():
        if expected_sha256 is None:
            return path
        try:
            verify_checksum(path, expected_sha256)
        except ChecksumMismatch:
            path.unlink()  # Corrupt cache entry: drop it and re-fetch.
        else:
            return path

    fetch(url, path, client=client, **fetch_kwargs)
    if expected_sha256 is not None:
        try:
            verify_checksum(path, expected_sha256)
        except ChecksumMismatch:
            path.unlink(missing_ok=True)
            raise
    return path


def extract_csv(path: str | Path, **read_csv_kwargs) -> pd.DataFrame:
    """Read a ``.zip``, ``.csv.gz`` or plain ``.csv`` archive into a DataFrame.

    Zip archives from the Binance archive contain exactly one CSV member.
    """
    path = Path(path)
    suffixes = [s.lower() for s in path.suffixes]

    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            members = [n for n in archive.namelist() if n.lower().endswith(".csv")]
            if len(members) != 1:
                raise DownloadError(f"expected exactly one CSV in {path.name}, found {members}")
            with archive.open(members[0]) as handle:
                return pd.read_csv(handle, **read_csv_kwargs)

    if ".gz" in suffixes:
        with gzip.open(path, "rb") as handle:
            return pd.read_csv(handle, **read_csv_kwargs)

    return pd.read_csv(path, **read_csv_kwargs)
