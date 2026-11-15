import numpy as np
import pandas as pd
import pytest
from scipy import stats

from hkrisk import var_models as vm

rng = np.random.default_rng(42)


def test_historical_toy_1_to_100():
    L = np.arange(1, 101)
    # linear quantile: h = 99*0.95 = 94.05 -> 95 + 0.05*(96-95) = 95.05
    assert vm.var_historical(L, 0.95) == pytest.approx(95.05)
    assert vm.es_historical(L, 0.95) == pytest.approx(np.mean([96, 97, 98, 99, 100]))


@pytest.mark.parametrize("seed", range(20))
def test_es_ge_var(seed):
    L = np.random.default_rng(seed).standard_t(4, 500)
    for a in (0.9, 0.95, 0.99):
        assert vm.es_historical(L, a) >= vm.var_historical(L, a)
        assert vm.es_normal(L, a) >= vm.var_normal(L, a)
        assert vm.es_t(L, a, nu=5) >= vm.var_t(L, a, nu=5)


def test_var_monotone_in_alpha():
    L = rng.normal(size=1000)
    alphas = [0.9, 0.95, 0.975, 0.99, 0.995]
    for f in (vm.var_historical, vm.var_normal):
        vals = [f(L, a) for a in alphas]
        assert np.all(np.diff(vals) > 0)


def test_bad_alpha():
    with pytest.raises(ValueError):
        vm.var_historical([1, 2, 3], 1.5)


def test_normal_on_standard_normal():
    L = np.random.default_rng(0).standard_normal(200_000)
    assert vm.var_normal(L, 0.99) == pytest.approx(2.326, abs=0.02)
    assert vm.es_normal(L, 0.99) == pytest.approx(2.665, abs=0.02)


def test_normal_closed_form_exact():
    L = rng.normal(size=300)
    mu, sd = L.mean(), L.std(ddof=1)
    assert vm.var_normal(L, 0.99) == pytest.approx(mu + sd * stats.norm.ppf(0.99), rel=1e-12)


def test_t_fatter_than_normal_at_99():
    L = np.random.default_rng(1).standard_normal(5000)
    assert vm.var_t(L, 0.99, nu=4) > vm.var_normal(L, 0.99)
    # but below the crossover (~97-98% for nu=4) t-VaR is smaller: same variance, more peaked
    assert vm.var_t(L, 0.95, nu=4) < vm.var_normal(L, 0.95)


def test_t_es_matches_numeric_integral():
    L = np.random.default_rng(2).standard_normal(1000)
    nu, a = 5.0, 0.99
    mu, s = L.mean(), L.std(ddof=1) * np.sqrt((nu - 2) / nu)
    q = stats.t.ppf(a, nu)
    tail_mean = stats.t.expect(lambda x: x, args=(nu,), lb=q) / (1 - a)
    assert vm.es_t(L, a, nu) == pytest.approx(mu + s * tail_mean, rel=1e-6)


def test_parametric_portfolio_equals_normal_on_pnl():
    R = pd.DataFrame(rng.multivariate_normal([0, 0.001, 0], [[1, .3, .1], [.3, 2, .2], [.1, .2, .5]],
                                             500) * 0.01)
    w = np.array([1e6, -2e5, 5e5])
    losses = -(R.to_numpy() @ w)
    assert vm.var_parametric_portfolio(w, R, 0.99) == pytest.approx(vm.var_normal(losses, 0.99),
                                                                     rel=1e-10)


def test_fit_t_df_recovers_nu():
    L = stats.t.rvs(5, size=20_000, random_state=3)
    assert vm.fit_t_df(L) == pytest.approx(5, rel=0.2)


def test_garch_fhs_units_and_persistence():
    # simulate GARCH(1,1) returns
    n, omega, a, b = 2000, 0.02, 0.08, 0.9
    r_rng = np.random.default_rng(5)
    s2, r = omega / (1 - a - b), []
    for _ in range(n):
        e = np.sqrt(s2) * r_rng.standard_normal()
        r.append(e)
        s2 = omega + a * e**2 + b * s2
    rets = np.array(r) / 100  # decimal
    out = vm.var_garch_fhs(rets, 0.99, value=1_000_000)
    assert out["persistence"] < 1
    assert out["params"]["alpha[1]"] == pytest.approx(a, abs=0.05)
    assert 0.001 < out["sigma_forecast"] < 0.05  # decimal, not percent
    assert out["var"] == pytest.approx(out["var_pct"] * 1_000_000)
    assert 5_000 < out["var"] < 100_000
    assert out["es"] > out["var"]
    fixed = vm.var_garch_fhs(rets, 0.99, value=1_000_000, params=out["_params_series"])
    assert fixed["var"] == pytest.approx(out["var"], rel=1e-6)
