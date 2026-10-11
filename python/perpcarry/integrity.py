"""Content evidence shared by ingestion, calibration and command-line reports.

This module does no downloading and has no research/tool dependencies.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

CHUNK_SIZE = 1 << 20


def sha256(path: str | Path, chunk_size: int = CHUNK_SIZE) -> str:
    """SHA-256 of a file, read in chunks so large archives stay out of memory."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def partition_fingerprint(directory: Path) -> dict[str, str]:
    return {path.name: sha256(path) for path in sorted(directory.glob("*.parquet"))}
