import pandas as pd
import pytest

from hkrisk import stress


def test_drawdown_window_toy():
    s = pd.Series([100, 120, 90, 110, 60, 80], index=pd.date_range("2020-01-01", periods=6))
    w = stress.find_drawdown_window(s, "2020-01-01", "2020-01-06")
    assert w["peak"] == "2020-01-02" and w["trough"] == "2020-01-05"
    assert w["drawdown"] == pytest.approx(-0.5)


def test_all_scenarios_run_with_proxies(snapshot, holdings):
    var99 = None
    from hkrisk.risk import compute_risk
    var99 = compute_risk(holdings, snapshot)["var"]
    for name in stress.load_scenarios():
        r = stress.run_historical_scenario(holdings, snapshot, name)
        assert r["total_pnl"] == pytest.approx(sum(p["pnl"] for p in r["positions"]))
        assert r["total_pnl"] < 0
    gfc = stress.run_historical_scenario(holdings, snapshot, "gfc_2008")
    assert set(gfc["proxied"]) == {"3690.HK", "1299.HK"}
    assert -gfc["total_pnl"] > 5 * var99


def test_hsi_shock_index_etf_beta_near_one(snapshot, holdings):
    r = stress.run_hsi_shock(holdings, snapshot, -0.2)
    etf = next(p for p in r["positions"] if p["ticker"] == "2800.HK")
    assert etf["beta"] == pytest.approx(1.0, abs=0.1)
    assert r["total_pnl"] < 0
