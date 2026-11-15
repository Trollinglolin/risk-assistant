"""Risk attribution: Euler components that sum exactly to the total."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from hkrisk import var_models as vm
from hkrisk.portfolio import position_values, returns_window
from hkrisk.risk import DEFAULT_WINDOW, compute_risk


def _frame(values: pd.Series, comp: np.ndarray, total: float) -> pd.DataFrame:
    df = pd.DataFrame({"position_value": values.values, "component": comp}, index=values.index)
    df["pct_of_total"] = df["component"] / total
    return df.sort_values("component", ascending=False)


def component_var_parametric(values: pd.Series, rets: pd.DataFrame, alpha: float) -> pd.DataFrame:
    """Normal (variance-covariance) VaR split by Euler.

    VaR(w) = -mu.w + z * sqrt(w'Sw) is homogeneous of degree 1, so
    CVaR_i = w_i * (-mu_i + z (Sw)_i / sigma_p) and sum_i CVaR_i = VaR exactly.
    """
    w = values.to_numpy(float)
    R = rets[values.index].to_numpy(float)
    S = np.cov(R, rowvar=False, ddof=vm.DDOF)
    sigma_p = float(np.sqrt(w @ S @ w))
    z = stats.norm.ppf(alpha)
    marginal = -R.mean(axis=0) + z * (S @ w) / sigma_p
    comp = w * marginal
    return _frame(values, comp, float(comp.sum()))


def component_var_historical(values: pd.Series, rets: pd.DataFrame, alpha: float) -> pd.DataFrame:
    """Historical VaR split by position.

    With the 'linear' quantile, VaR = (1-g) L_(j) + g L_(j+1) for two order statistics,
    so the per-position losses on those two scenario days (same weights) sum to VaR.
    """
    w = values.to_numpy(float)
    pos_loss = -(rets[values.index].to_numpy(float) * w)
    L = pos_loss.sum(axis=1)
    order = np.argsort(L, kind="stable")
    h = (len(L) - 1) * alpha
    j = int(np.floor(h))
    g = h - j
    comp = (1 - g) * pos_loss[order[j]] + (g * pos_loss[order[min(j + 1, len(L) - 1)]])
    return _frame(values, comp, float(comp.sum()))


def component_es_historical(values: pd.Series, rets: pd.DataFrame, alpha: float) -> pd.DataFrame:
    """CES_i = mean over tail days (L >= VaR) of -V_i R_i,t; sums to historical ES exactly."""
    w = values.to_numpy(float)
    pos_loss = -(rets[values.index].to_numpy(float) * w)
    L = pos_loss.sum(axis=1)
    tail = L >= vm.var_historical(L, alpha)
    comp = pos_loss[tail].mean(axis=0)
    return _frame(values, comp, float(comp.sum()))


def contributions(
    holdings, prices, as_of=None, method: str = "historical", measure: str = "var",
    alpha: float = 0.99, window: int = DEFAULT_WINDOW,
) -> dict:
    vals = position_values(holdings, prices, as_of)
    rets = returns_window(holdings, prices, as_of, window)
    if measure == "es":
        if method != "historical":
            raise ValueError("component ES is available for method='historical' only")
        df = component_es_historical(vals, rets, alpha)
    elif method == "historical":
        df = component_var_historical(vals, rets, alpha)
    elif method == "normal":
        df = component_var_parametric(vals, rets, alpha)
    else:
        raise ValueError("component VaR is available for 'historical' and 'normal'")
    return {
        "method": method, "measure": measure, "alpha": alpha, "window": window,
        "as_of": vals.attrs["as_of"].strftime("%Y-%m-%d"), "currency": "HKD",
        "total": float(df["component"].sum()),
        "components": [
            {"ticker": t, "position_value": float(r.position_value),
             "component": float(r.component), "pct_of_total": float(r.pct_of_total)}
            for t, r in df.iterrows()
        ],
    }


def explain_change(
    holdings, prices, start_date=None, end_date=None, method: str = "historical",
    alpha: float = 0.99, window: int = DEFAULT_WINDOW, lookback_days: int = 5, top_n: int = 3,
) -> dict:
    """Why did VaR move between start_date and end_date (default: last 5 trading days)?

    Splits dVaR exactly into
      * price/position effect: same start window, positions revalued at end prices;
      * window-roll effect: positions at end, window rolled from start to end;
    and per-position deltas of the component VaR.
    """
    if method not in ("historical", "normal"):
        raise ValueError("explain_change supports method 'historical' or 'normal'")
    idx = prices.loc[: pd.Timestamp(end_date)].dropna(subset=list(holdings)).index if end_date \
        else prices.dropna(subset=list(holdings)).index
    end = idx[-1]
    start = idx[idx <= pd.Timestamp(start_date)][-1] if start_date else idx[-1 - lookback_days]
    c0 = contributions(holdings, prices, start, method, "var", alpha, window)
    c1 = contributions(holdings, prices, end, method, "var", alpha, window)
    var0, var1 = c0["total"], c1["total"]

    v_end = position_values(holdings, prices, end)
    r_start = returns_window(holdings, prices, start, window)
    r_end = returns_window(holdings, prices, end, window)
    fn = vm.var_historical if method == "historical" else vm.var_normal
    var_mixed = fn(-(r_start[v_end.index] @ v_end.values), alpha)

    comp0 = {c["ticker"]: c["component"] for c in c0["components"]}
    deltas = sorted(
        ({"ticker": c["ticker"], "component_start": comp0[c["ticker"]],
          "component_end": c["component"], "delta": c["component"] - comp0[c["ticker"]]}
         for c in c1["components"]),
        key=lambda d: abs(d["delta"]), reverse=True,
    )
    entered = r_end.index.difference(r_start.index)
    left = r_start.index.difference(r_end.index)
    loss_end = -(r_end[v_end.index] @ v_end.values)
    loss_left = -(r_start.loc[left, v_end.index] @ v_end.values)
    return {
        "method": method, "alpha": alpha, "window": window, "currency": "HKD",
        "start_date": start.strftime("%Y-%m-%d"), "end_date": end.strftime("%Y-%m-%d"),
        "as_of": end.strftime("%Y-%m-%d"),
        "var_start": var0, "var_end": var1, "var_change": var1 - var0,
        "price_position_effect": var_mixed - var0,
        "window_roll_effect": var1 - var_mixed,
        "position_deltas": deltas,
        "top_contributors_end": c1["components"][:top_n],
        "days_entered": [{"date": d.strftime("%Y-%m-%d"), "loss": float(loss_end[d])}
                         for d in entered],
        "days_left": [{"date": d.strftime("%Y-%m-%d"), "loss": float(loss_left[d])}
                      for d in left],
        "portfolio_value_start": float(position_values(holdings, prices, start).sum()),
        "portfolio_value_end": float(v_end.sum()),
    }


def risk_with_components(holdings, prices, as_of=None, alpha=0.99, window=DEFAULT_WINDOW):
    """Convenience used by the report."""
    return compute_risk(holdings, prices, as_of, "historical", alpha, window), contributions(
        holdings, prices, as_of, "historical", "es", alpha, window)
