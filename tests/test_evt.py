import numpy as np
import pytest
from scipy import stats

from hkrisk import evt
from hkrisk import var_models as vm


def test_xi_recovers_t4_tail():
    L = stats.t.rvs(4, size=50_000, random_state=11)
    xi, *_ = evt.fit_gpd(L, 0.97)
    assert xi == pytest.approx(0.25, abs=0.08)


def test_evt_999_reasonable_vs_truth():
    L = stats.t.rvs(4, size=2000, random_state=7)
    r = evt.var_es_evt(L, 0.999, 0.95)
    truth = stats.t.ppf(0.999, 4)
    assert r["var"] == pytest.approx(truth, rel=0.35)
    assert r["var"] > vm.var_historical(L, 0.99)
    assert r["es"] > r["var"]


def test_exponential_limit_continuous():
    a = evt.var_evt(1e-9, 1.0, 2.0, 50, 1000, 0.99)
    b = evt.var_evt(1e-4, 1.0, 2.0, 50, 1000, 0.99)
    assert a == pytest.approx(b, rel=1e-3)


def test_alpha_must_exceed_threshold():
    with pytest.raises(ValueError):
        evt.var_es_evt(np.random.default_rng(0).normal(size=500), 0.9, 0.95)
