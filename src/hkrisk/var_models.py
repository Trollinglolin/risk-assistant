"""VaR / ES models. Convention: losses are positive, L = -PnL; alpha=0.99 -> 99% VaR."""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from scipy import stats

DDOF = 1  # match R's sd() and pandas .std()


def _arr(x) -> np.ndarray:
    a = np.asarray(x, dtype=float)
    return a[~np.isnan(a)]


def _check_alpha(alpha: float) -> None:
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")


# ---------- historical ----------

def var_historical(losses, alpha: float) -> float:
    """alpha-quantile of losses, numpy 'linear' method == R quantile type=7."""
    _check_alpha(alpha)
    return float(np.quantile(_arr(losses), alpha, method="linear"))


def es_historical(losses, alpha: float) -> float:
    """Mean loss on days at least as bad as VaR."""
    L = _arr(losses)
    v = var_historical(L, alpha)
    return float(L[L >= v].mean())


# ---------- normal ----------

def var_normal(losses, alpha: float) -> float:
    _check_alpha(alpha)
    L = _arr(losses)
    return float(L.mean() + L.std(ddof=DDOF) * stats.norm.ppf(alpha))


def es_normal(losses, alpha: float) -> float:
    _check_alpha(alpha)
    L = _arr(losses)
    z = stats.norm.ppf(alpha)
    return float(L.mean() + L.std(ddof=DDOF) * stats.norm.pdf(z) / (1 - alpha))


# ---------- Student-t ----------

def fit_t_df(losses, lo: float = 2.5, hi: float = 100.0) -> float:
    """MLE degrees of freedom (scipy t.fit), clipped to [lo, hi] for stability."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        nu, _, _ = stats.t.fit(_arr(losses))
    return float(np.clip(nu, lo, hi))


def _t_scale(sigma: float, nu: float) -> float:
    if nu <= 2:
        raise ValueError("nu must be > 2 for finite variance")
    return sigma * np.sqrt((nu - 2) / nu)


def var_t(losses, alpha: float, nu: float | None = None) -> float:
    _check_alpha(alpha)
    L = _arr(losses)
    nu = fit_t_df(L) if nu is None else nu
    s = _t_scale(L.std(ddof=DDOF), nu)
    return float(L.mean() + s * stats.t.ppf(alpha, nu))


def es_t(losses, alpha: float, nu: float | None = None) -> float:
    _check_alpha(alpha)
    L = _arr(losses)
    nu = fit_t_df(L) if nu is None else nu
    s = _t_scale(L.std(ddof=DDOF), nu)
    q = stats.t.ppf(alpha, nu)
    return float(L.mean() + s * stats.t.pdf(q, nu) / (1 - alpha) * (nu + q**2) / (nu - 1))


# ---------- variance-covariance for a portfolio ----------

def var_parametric_portfolio(positions, returns_window: pd.DataFrame, alpha: float) -> float:
    """Normal VaR of P&L = R @ w using mean vector and covariance (ddof=1)."""
    _check_alpha(alpha)
    w = np.asarray(positions, dtype=float)
    R = np.asarray(returns_window, dtype=float)
    mu_L = -float(R.mean(axis=0) @ w)
    sigma_p = float(np.sqrt(w @ np.cov(R, rowvar=False, ddof=DDOF) @ w))
    return mu_L + sigma_p * float(stats.norm.ppf(alpha))


# ---------- GARCH(1,1) filtered historical simulation ----------

def fit_garch(returns, dist: str = "t"):
    """Fit constant-mean GARCH(1,1) to decimal returns; returns the arch result (pct units)."""
    from arch import arch_model

    am = arch_model(np.asarray(returns, float) * 100, mean="Constant", vol="GARCH",
                    p=1, q=1, dist=dist, rescale=False)
    return am.fit(disp="off", show_warning=False)


def var_garch_fhs(
    returns, alpha: float, value: float = 1.0, params: pd.Series | None = None,
    dist: str = "t",
) -> dict:
    """FHS: VaR = -(mu + sigma_{T+1} * q_{1-alpha}(z)), in units of ``value`` (e.g. HKD).

    ``returns`` are decimal portfolio returns. If ``params`` is given the model is not
    re-estimated, only filtered with those parameters (fast, for backtests).
    """
    from arch import arch_model

    _check_alpha(alpha)
    r = np.asarray(returns, float)
    if params is None:
        res = fit_garch(r, dist)
    else:
        am = arch_model(r * 100, mean="Constant", vol="GARCH", p=1, q=1, dist=dist,
                        rescale=False)
        res = am.fix(params)
    z = np.asarray(res.std_resid, float)
    z = z[~np.isnan(z)]
    mu = float(res.params["mu"]) / 100
    sigma_next = float(np.sqrt(res.forecast(horizon=1, reindex=False).variance.values[-1, 0])) / 100
    qz = float(np.quantile(z, 1 - alpha, method="linear"))
    tail = z[z <= qz]
    var_pct = -(mu + sigma_next * qz)
    es_pct = -(mu + sigma_next * tail.mean())
    p = res.params
    return {
        "var": var_pct * value,
        "es": es_pct * value,
        "var_pct": var_pct,
        "es_pct": es_pct,
        "sigma_forecast": sigma_next,
        "persistence": float(p["alpha[1]"] + p["beta[1]"]),
        "params": {k: float(v) for k, v in p.items()},
        "_params_series": p,
        "_cond_vol": np.asarray(res.conditional_volatility) / 100,
    }
