import pandas as pd
import pytest

from hkrisk.data import FIXTURE_PATH, SNAPSHOT_PATH
from hkrisk.portfolio import load_portfolio


@pytest.fixture(scope="session")
def small_prices() -> pd.DataFrame:
    return pd.read_parquet(FIXTURE_PATH)


@pytest.fixture(scope="session")
def snapshot() -> pd.DataFrame:
    return pd.read_parquet(SNAPSHOT_PATH)


@pytest.fixture(scope="session")
def holdings() -> dict[str, float]:
    return load_portfolio()


def pytest_collection_modifyitems(config, items):
    if config.getoption("-m") and "live" in config.getoption("-m"):
        return
    skip = pytest.mark.skip(reason="live test: run with  pytest -m live")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _no_local_llm_limits(monkeypatch, tmp_path):
    """Tests must not pick up rate limits from a developer's .env or touch ~/.cache quota files."""
    for k in ("LLM_RPM", "LLM_TPM", "LLM_RPD"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("hkrisk.agent.ratelimit.STATE_DIR", tmp_path)
