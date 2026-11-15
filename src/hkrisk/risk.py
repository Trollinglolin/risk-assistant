"""One entry point the API / agent / report call: risk numbers for the current book."""

from __future__ import annotations

import numpy as np
import pandas as pd

from hkrisk import evt
from hkrisk import var_models as vm
from hkrisk.portfolio import hypothetical_pnl, position_values

METHODS = ("historical", "normal", "t", "garch", "evt")
CURRENCY = "HKD"
DEFAULT_WINDOW = 500
DEFAULT_EVT_Q = 0.95


def var_es_from_pnl(
    pnl, method: str, alpha: float, value: float, nu: float | None = None,
    garch_params=None, evt_q: float = DEFAULT_EVT_Q,
) -> dict:
    """VaR/ES (HKD, positive = loss) of a hypothetical P&L sample for one method."""
    pnl = np.asarray(pnl, float)
    losses = -pnl
    extra: dict = {}
    if method == "historical":
        var, es = vm.var_historical(losses, alpha), vm.es_historical(losses, alpha)
    elif method == "normal":
        var, es = vm.var_normal(losses, alpha), vm.es_normal(losses, alpha)
    elif method == "t":
        nu = vm.fit_t_df(losses) if nu is None else nu
        var, es = vm.var_t(losses, alpha, nu), vm.es_t(losses, alpha, nu)
        extra["nu"] = nu
    elif method == "garch":
        g = vm.var_garch_fhs(pnl / value, alpha, value=value, params=garch_params)
        var, es = g["var"], g["es"]
        extra.update(sigma_forecast=g["sigma_forecast"], persistence=g["persistence"],
                     garch_params=g["params"], _params_series=g["_params_series"])
    elif method == "evt":
        # threshold must sit below alpha: 0.95 by default, 0.90 for a 95% VaR
        evt_q = min(evt_q, round(2 * alpha - 1, 4))
        e = evt.var_es_evt(losses, alpha, evt_q)
        var, es = e["var"], e["es"]
        extra.update(xi=e["xi"], beta=e["beta"], threshold=e["u"], n_exceed=e["n_u"],
                     threshold_q=evt_q)
    else:
        raise ValueError(f"unknown method {method!r}; choose from {METHODS}")
    return {"var": float(var), "es": float(es), **extra}


def compute_risk(
    holdings: dict[str, float], prices: pd.DataFrame, as_of=None,
    method: str = "historical", alpha: float = 0.99, window: int = DEFAULT_WINDOW,
    horizon_days: int = 1,
) -> dict:
    vm._check_alpha(alpha)
    if method not in METHODS:
        raise ValueError(f"unknown method {method!r}; choose from {METHODS}")
    vals = position_values(holdings, prices, as_of)
    value = float(vals.sum())
    pnl = hypothetical_pnl(holdings, prices, as_of, window)
    r = var_es_from_pnl(pnl.values, method, alpha, value)
    scale = float(np.sqrt(horizon_days))  # sqrt-time rule, assumes iid returns
    out = {
        "method": method,
        "alpha": alpha,
        "as_of": vals.attrs["as_of"].strftime("%Y-%m-%d"),
        "window": window,
        "horizon_days": horizon_days,
        "currency": CURRENCY,
        "portfolio_value": value,
        "var": r["var"] * scale,
        "es": r["es"] * scale,
        "var_pct": r["var"] * scale / value,
        "es_pct": r["es"] * scale / value,
    }
    out.update({k: v for k, v in r.items() if k not in ("var", "es") and not k.startswith("_")})
    return out
