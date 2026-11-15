import numpy as np
import pytest

from hkrisk import backtest as bt
from hkrisk.portfolio import hypothetical_pnl
from hkrisk.var_models import var_historical


def test_kupiec_zero_exceptions():
    r = bt.kupiec_pof(np.zeros(250, bool), 0.99)
    assert np.isfinite(r["lr"]) and r["exceptions"] == 0
    assert r["lr"] == pytest.approx(-2 * 250 * np.log(0.99))


def test_kupiec_formula():
    e = np.zeros(1000, bool)
    e[:20] = True
    T, x, p = 1000, 20, 0.01
    lr = -2 * ((T - x) * np.log(1 - p) + x * np.log(p)) + 2 * (
        (T - x) * np.log(1 - x / T) + x * np.log(x / T))
    assert bt.kupiec_pof(e, 0.99)["lr"] == pytest.approx(lr)


def test_christoffersen_no_consecutive():
    e = np.zeros(500, int)
    e[[10, 100, 300]] = 1
    r = bt.christoffersen(e)
    assert r["n11"] == 0 and np.isfinite(r["lr_ind"]) and np.isfinite(r["lr_cc"])


def test_christoffersen_detects_clustering():
    e = np.zeros(1000, int)
    e[500:510] = 1
    assert bt.christoffersen(e)["reject_ind"]


def test_christoffersen_all_zero():
    r = bt.christoffersen(np.zeros(300, int))
    assert r["lr_ind"] == 0


@pytest.mark.parametrize("T,lo,hi", [(1000, 0.03, 0.07), (250, 0.0, 0.12)])
def test_kupiec_size_monte_carlo(T, lo, hi):
    rng = np.random.default_rng(2024)
    rej = np.mean([bt.kupiec_pof(rng.random(T) < 0.01, 0.99)["reject"] for _ in range(2000)])
    assert lo <= rej <= hi, rej


def test_traffic_light_zones():
    assert bt.traffic_light(np.r_[np.ones(4), np.zeros(246)])["zone"] == "green"
    y = bt.traffic_light(np.r_[np.ones(7), np.zeros(243)])
    assert y["zone"] == "yellow" and y["plus_factor"] == 0.65 and y["multiplier"] == 3.65
    assert bt.traffic_light(np.ones(10))["zone"] == "red"


def test_rolling_var_is_out_of_sample(snapshot, holdings):
    df = bt.rolling_var(holdings, snapshot, "historical", 0.99, 500,
                        start="2026-09-01", end="2026-10-30")
    t = df.index[5]
    prev = snapshot.loc[:t].index[-2]
    pnl = hypothetical_pnl(holdings, snapshot, prev, 500)
    assert df.loc[t, "var"] == pytest.approx(var_historical(-pnl.values, 0.99), rel=1e-12)
    # realised loss on t uses t-1 values and t returns
    px = snapshot.loc[[prev, t], list(holdings)]
    v = px.loc[prev] * np.array([holdings[k] for k in px.columns])
    assert df.loc[t, "loss"] == pytest.approx(-(v * (px.loc[t] / px.loc[prev] - 1)).sum())
