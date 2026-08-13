"""Test-wide safety net: no test may touch the real data root.

Without this, anything calling ``cached_fetch`` writes into the project's ``data/.cache/``
under the archive's own filename. A test serving a synthetic payload then leaves a file
that a later *real* backfill will happily reuse -- fabricated trades entering the research
corpus, looking exactly like archive data.

That is not hypothetical: it happened during M1-T1 development and was caught by the
pre-push review, after a 199-row punched fixture had already landed in ``data/.cache/``.
"""

import pytest

from perpcarry.storage import DATA_ROOT_ENV_VAR


@pytest.fixture(autouse=True)
def isolated_data_root(tmp_path, monkeypatch):
    """Point every test's data root -- and therefore its download cache -- at tmp."""
    root = tmp_path / "data_root"
    root.mkdir()
    monkeypatch.setenv(DATA_ROOT_ENV_VAR, str(root))
    return root
