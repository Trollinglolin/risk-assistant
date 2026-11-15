import numpy as np
import pytest

from hkrisk import attribution as at
from hkrisk.portfolio import position_values, returns_window
from hkrisk.risk import compute_risk


@pytest.fixture(scope="module")
def setup(small_prices, holdings):
    v = position_values(holdings, small_prices)
    r = returns_window(holdings, small_prices, None, 250)
    return v, r


def test_parametric_sums_to_normal_var(small_prices, holdings, setup):
    v, r = setup
    df = at.component_var_parametric(v, r, 0.99)
    total = compute_risk(holdings, small_prices, None, "normal", 0.99, 250)["var"]
    assert df["component"].sum() == pytest.approx(total, abs=1e-6)
    assert df["pct_of_total"].sum() == pytest.approx(1.0)


def test_historical_var_components_sum(small_prices, holdings, setup):
    v, r = setup
    for a in (0.95, 0.99):
        df = at.component_var_historical(v, r, a)
        total = compute_risk(holdings, small_prices, None, "historical", a, 250)["var"]
        assert df["component"].sum() == pytest.approx(total, abs=1e-6)


def test_component_es_sums_to_es(small_prices, holdings, setup):
    v, r = setup
    df = at.component_es_historical(v, r, 0.975)
    total = compute_risk(holdings, small_prices, None, "historical", 0.975, 250)["es"]
    assert df["component"].sum() == pytest.approx(total, abs=1e-6)


def test_zero_position_has_zero_component(small_prices, holdings):
    h = dict(holdings, **{"0700.HK": 0})
    for m in ("historical", "normal"):
        c = at.contributions(h, small_prices, None, m, "var", 0.99, 250)
        comp = {x["ticker"]: x["component"] for x in c["components"]}
        assert comp["0700.HK"] == 0


def test_hedge_negative_component(small_prices, holdings):
    h = dict(holdings)
    h["2800.HK"] = -60_000  # short the index ETF as a hedge
    c = at.contributions(h, small_prices, None, "normal", "var", 0.99, 250)
    comp = {x["ticker"]: x["component"] for x in c["components"]}
    assert comp["2800.HK"] < 0


def test_explain_change_decomposition(snapshot, holdings):
    e = at.explain_change(holdings, snapshot, method="historical")
    assert e["var_change"] == pytest.approx(e["price_position_effect"] + e["window_roll_effect"])
    assert e["var_change"] == pytest.approx(sum(d["delta"] for d in e["position_deltas"]))
    assert len(e["days_entered"]) == len(e["days_left"]) == 5
    assert np.isclose(e["var_end"], compute_risk(holdings, snapshot)["var"])
