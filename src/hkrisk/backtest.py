"""Rolling out-of-sample VaR backtests: Kupiec POF, Christoffersen, Basel traffic light."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats
from scipy.special import xlogy

from hkrisk import var_models as vm
from hkrisk.data import align_prices
from hkrisk.portfolio import simple_returns
from hkrisk.risk import DEFAULT_WINDOW, var_es_from_pnl

TL_TABLE = {5: 0.40, 6: 0.50, 7: 0.65, 8: 0.75, 9: 0.85}


def rolling_var(
    holdings: dict[str, float], prices: pd.DataFrame, method: str = "historical",
    alpha: float = 0.99, window: int = DEFAULT_WINDOW, start=None, end=None,
    refit_every: int = 20,
) -> pd.DataFrame:
    """For each test day t: positions valued at t-1 prices, fit on returns [t-W, t-1],
    forecast VaR_t, then compare with the realised loss L_t = -sum_i V_i,t-1 R_i,t.

    Share counts are fixed (hypothetical P&L), so trading never leaks into the test.
    GARCH params and Student-t nu are re-estimated every ``refit_every`` days and
    held fixed in between (GARCH still filters daily).
    """
    tickers = list(holdings)
    px = align_prices(prices.loc[: pd.Timestamp(end)] if end else prices, tickers)
    rets = simple_returns(px)
    shares = np.array([holdings[t] for t in tickers])
    P = px[tickers].to_numpy()
    R = rets[tickers].to_numpy()
    dates = rets.index
    first = window
    if start is not None:
        first = max(first, int(dates.searchsorted(pd.Timestamp(start))))
    rows = []
    garch_params = nu = None
    for k, i in enumerate(range(first, len(dates))):
        V = shares * P[i]  # P has one more row than R: P[i] is the close on day dates[i-1]
        pnl_win = R[i - window:i] @ V
        value = float(V.sum())
        refit = k % refit_every == 0
        if method == "garch":
            r = var_es_from_pnl(pnl_win, "garch", alpha, value,
                                garch_params=None if refit else garch_params)
            if refit:
                garch_params = r["_params_series"]
        elif method == "t":
            if refit:
                nu = vm.fit_t_df(-pnl_win)
            r = var_es_from_pnl(pnl_win, "t", alpha, value, nu=nu)
        else:
            r = var_es_from_pnl(pnl_win, method, alpha, value)
        loss = -float(R[i] @ V)
        rows.append((dates[i], r["var"], r["es"], loss, value))
    df = pd.DataFrame(rows, columns=["date", "var", "es", "loss", "value"]).set_index("date")
    df["exception"] = df["loss"] > df["var"]
    return df


def kupiec_pof(exceptions, alpha: float = 0.99, level: float = 0.05) -> dict:
    e = np.asarray(exceptions, bool)
    T, x = len(e), int(e.sum())
    p = 1 - alpha
    phat = x / T
    ll0 = xlogy(T - x, 1 - p) + xlogy(x, p)
    ll1 = xlogy(T - x, 1 - phat) + xlogy(x, phat)
    lr = float(-2 * (ll0 - ll1))
    pv = float(stats.chi2.sf(lr, 1))
    return {"T": T, "exceptions": x, "expected": T * p, "rate": phat, "lr": lr,
            "p_value": pv, "reject": pv < level}


def _div(a, b):
    return a / b if b else 0.0


def christoffersen(exceptions, alpha: float = 0.99, level: float = 0.05) -> dict:
    e = np.asarray(exceptions, int)
    prev, curr = e[:-1], e[1:]
    n00 = int(((prev == 0) & (curr == 0)).sum())
    n01 = int(((prev == 0) & (curr == 1)).sum())
    n10 = int(((prev == 1) & (curr == 0)).sum())
    n11 = int(((prev == 1) & (curr == 1)).sum())
    pi01, pi11 = _div(n01, n00 + n01), _div(n11, n10 + n11)
    pi = _div(n01 + n11, n00 + n01 + n10 + n11)
    ll0 = xlogy(n00 + n10, 1 - pi) + xlogy(n01 + n11, pi)
    ll1 = (xlogy(n00, 1 - pi01) + xlogy(n01, pi01)
           + xlogy(n10, 1 - pi11) + xlogy(n11, pi11))
    lr_ind = float(max(-2 * (ll0 - ll1), 0.0))
    pof = kupiec_pof(e.astype(bool), alpha, level)
    lr_cc = pof["lr"] + lr_ind
    p_ind, p_cc = float(stats.chi2.sf(lr_ind, 1)), float(stats.chi2.sf(lr_cc, 2))
    return {"n00": n00, "n01": n01, "n10": n10, "n11": n11, "pi01": pi01, "pi11": pi11,
            "lr_ind": lr_ind, "p_value_ind": p_ind, "reject_ind": p_ind < level,
            "lr_cc": lr_cc, "p_value_cc": p_cc, "reject_cc": p_cc < level}


def traffic_light(exceptions_last_250) -> dict:
    """Basel (1996) zones for 99% VaR over 250 days."""
    n = int(np.sum(exceptions_last_250))
    if n <= 4:
        zone, plus = "green", 0.0
    elif n <= 9:
        zone, plus = "yellow", TL_TABLE[n]
    else:
        zone, plus = "red", 1.0
    return {"zone": zone, "count": n, "plus_factor": plus, "multiplier": 3.0 + plus}


def rolling_traffic_light(exceptions: pd.Series, n: int = 250) -> pd.DataFrame:
    counts = exceptions.astype(int).rolling(n).sum().dropna().astype(int)
    zones = counts.map(lambda c: traffic_light(np.ones(c))["zone"])
    return pd.DataFrame({"count": counts, "zone": zones})


def summarize(bt: pd.DataFrame, alpha: float) -> dict:
    exc = bt["exception"].to_numpy()
    k, c = kupiec_pof(exc, alpha), christoffersen(exc, alpha)
    rtl = rolling_traffic_light(bt["exception"])
    zone_counts = rtl["zone"].value_counts().reindex(["green", "yellow", "red"], fill_value=0)
    return {
        "start": bt.index[0].strftime("%Y-%m-%d"), "end": bt.index[-1].strftime("%Y-%m-%d"),
        "days": len(bt), "years": round(len(bt) / 250, 2), "exceptions": k["exceptions"],
        "expected": round(k["expected"], 2), "kupiec_lr": k["lr"], "kupiec_p": k["p_value"],
        "kupiec_reject": k["reject"], "christoffersen_ind_p": c["p_value_ind"],
        "christoffersen_cc_p": c["p_value_cc"], "cc_reject": c["reject_cc"],
        "latest_250d": traffic_light(exc[-250:]),
        "rolling_zone_days": {z: int(v) for z, v in zone_counts.items()},
        "worst_250d_count": int(rtl["count"].max()) if len(rtl) else None,
    }
