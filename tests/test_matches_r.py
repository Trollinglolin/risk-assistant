"""Python engine vs independent R implementation (reference/r_results.csv)."""

import numpy as np
import pandas as pd
import pytest

from hkrisk import PROJECT_ROOT, evt
from hkrisk import var_models as vm
from hkrisk.backtest import kupiec_pof

REF = PROJECT_ROOT / "reference"
pytestmark = pytest.mark.skipif(not (REF / "r_results.csv").exists(), reason="run R first")


@pytest.fixture(scope="module")
def r():
    return pd.read_csv(REF / "r_results.csv").set_index("metric")["value"].to_dict()


@pytest.fixture(scope="module")
def inp():
    return pd.read_csv(REF / "input.csv")


def test_closed_forms_exact(r, inp):
    L = -inp["pnl"].to_numpy()
    py = {
        "hist_var": vm.var_historical(L, 0.99), "hist_es": vm.es_historical(L, 0.99),
        "normal_var": vm.var_normal(L, 0.99), "normal_es": vm.es_normal(L, 0.99),
        "t5_var": vm.var_t(L, 0.99, 5), "t5_es": vm.es_t(L, 0.99, 5),
    }
    for k, v in py.items():
        np.testing.assert_allclose(v, r[k], rtol=1e-8, err_msg=k)


def test_kupiec_exact(r):
    e = pd.read_csv(REF / "exceptions.csv")["exception"].to_numpy()
    np.testing.assert_allclose(kupiec_pof(e, 0.99)["lr"], r["kupiec_lr"], rtol=1e-8)


def test_garch_params_close(r, inp):
    p = vm.fit_garch(inp["ret"].to_numpy()).params
    # different optimisers (rugarch solnp/hybrid vs arch SLSQP): a few percent
    np.testing.assert_allclose(p["alpha[1]"] + p["beta[1]"], r["garch_alpha"] + r["garch_beta"],
                               rtol=0.03)
    np.testing.assert_allclose(p["beta[1]"], r["garch_beta"], rtol=0.05)
    np.testing.assert_allclose(p["nu"], r["garch_nu"], rtol=0.15)


def test_evt_close(r, inp):
    L = -inp["pnl"].to_numpy()
    xi, beta, u, n_u, n = evt.fit_gpd(L, 0.95)
    np.testing.assert_allclose(xi, r["evt_xi"], rtol=0.01)
    np.testing.assert_allclose(beta, r["evt_beta"], rtol=0.01)
    np.testing.assert_allclose(evt.var_evt(xi, beta, u, n_u, n, 0.99), r["evt_var"], rtol=1e-3)
