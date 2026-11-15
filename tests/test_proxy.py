import numpy as np
import pandas as pd
import pytest

from hkrisk import proxy
from hkrisk.service import RiskService
from hkrisk.universe import HSI_SNAPSHOT_PATH, load_universe


def _toy(n=400, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-01", periods=n)
    m = rng.normal(0, 0.01, n)
    stock = 1.5 * m + rng.normal(0, 0.002, n)
    px = pd.DataFrame({"^HSI": 100 * np.cumprod(1 + m), "NEW": 10 * np.cumprod(1 + stock)}, idx)
    px.iloc[:200, 1] = np.nan  # listed on day 200
    return px


def test_backfill_keeps_real_prices_and_recovers_beta():
    px = _toy()
    filled, info = proxy.beta_backfill(px, beta_obs=150)
    real = px["NEW"].dropna()
    pd.testing.assert_series_equal(filled.loc[real.index, "NEW"], real)
    assert filled["NEW"].notna().all()
    assert info["NEW"]["beta"] == pytest.approx(1.5, abs=0.1)
    # proxied returns are exactly beta x index returns
    r = filled.pct_change().iloc[1:200]
    np.testing.assert_allclose(r["NEW"], info["NEW"]["beta"] * r["^HSI"], rtol=1e-9)


def test_drop_stale_prefix_removes_reused_code_print():
    px = _toy()
    px.iloc[150, 1] = 3.0  # stray print, then a 49-row gap before the real listing
    cleaned, dropped = proxy.drop_stale_prefix(px, max_gap=20)
    assert dropped == {"NEW": 1} and cleaned["NEW"].first_valid_index() == px.index[200]


def test_universe_is_the_official_95():
    u = load_universe()
    assert len(u) == 95 and len({c["ticker"] for c in u}) == 95
    assert sum(c["weight_pct"] for c in u) == pytest.approx(100, abs=0.1)


@pytest.mark.skipif(not HSI_SNAPSHOT_PATH.exists(), reason="HSI snapshot not built")
def test_hsi_book_loads_and_backtests():
    s = RiskService.load("hsi")
    p = s.portfolio()
    assert p["n_positions"] == 95 and p["portfolio"] == "hsi"
    assert {"0300.HK"} <= set(s.repairs["stale_prefix_dropped"])
    assert s.var("historical")["var"] > 0
    st = s.stress("gfc_2008")
    assert "3750.HK" in st["proxied"]  # CATL listed in 2025: proxied, not backfilled prices
