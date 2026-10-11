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


@pytest.fixture
def funding_frame_factory():
    """Synthetic complete funding windows; never copied from exchange records."""
    import numpy as np
    import pandas as pd

    def build(start="2025-07-01", end="2025-10-03", symbol="TESTUSDT", seed=1729):
        times = pd.date_range(start, end, inclusive="left", freq="8h", tz="UTC")
        innovations = np.random.default_rng(seed).normal(0.00002, 0.000005, len(times))
        rates = innovations.copy()
        for i in range(1, len(rates)):
            rates[i] += 0.65 * rates[i - 1]
        return pd.DataFrame(
            {
                "funding_time": times.as_unit("ms").asi8 + 137,
                "symbol": symbol,
                "funding_rate": rates,
                "funding_interval_hours": 8,
                "date": times.strftime("%Y-%m-%d"),
            }
        )

    return build
