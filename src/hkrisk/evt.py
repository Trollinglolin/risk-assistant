"""Extreme value theory: peaks over threshold with a Generalised Pareto tail."""

from __future__ import annotations

import warnings

import numpy as np
from scipy import stats

XI_EPS = 1e-6


def fit_gpd(losses, threshold_q: float = 0.95) -> tuple[float, float, float, int, int]:
    """Fit GPD(xi, beta) to excesses over u = quantile(losses, threshold_q).

    Returns (xi, beta, u, n_u, n). MLE with loc fixed at 0.
    """
    L = np.asarray(losses, float)
    L = L[~np.isnan(L)]
    u = float(np.quantile(L, threshold_q))
    exc = L[L > u] - u
    if len(exc) < 5:
        raise ValueError(f"only {len(exc)} exceedances over threshold; lower threshold_q")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        xi, _, beta = stats.genpareto.fit(exc, floc=0)
    return float(xi), float(beta), u, len(exc), len(L)


def var_evt(xi: float, beta: float, u: float, n_u: int, n: int, alpha: float) -> float:
    tail = (n / n_u) * (1 - alpha)
    if abs(xi) < XI_EPS:  # exponential limit
        return float(u - beta * np.log(tail))
    return float(u + (beta / xi) * (tail ** (-xi) - 1))


def es_evt(xi: float, beta: float, u: float, n_u: int, n: int, alpha: float) -> float:
    if xi >= 1:
        raise ValueError("ES undefined for xi >= 1")
    v = var_evt(xi, beta, u, n_u, n, alpha)
    return float((v + beta - xi * u) / (1 - xi))


def var_es_evt(losses, alpha: float, threshold_q: float = 0.95) -> dict:
    xi, beta, u, n_u, n = fit_gpd(losses, threshold_q)
    if alpha <= threshold_q:
        raise ValueError(f"alpha ({alpha}) must exceed threshold_q ({threshold_q}) for POT")
    # xi >= 1 means the fitted tail has infinite mean: ES is undefined (NaN), VaR still is.
    es = es_evt(xi, beta, u, n_u, n, alpha) if xi < 1 else float("nan")
    return {
        "var": var_evt(xi, beta, u, n_u, n, alpha),
        "es": es,
        "xi": xi, "beta": beta, "u": u, "n_u": n_u, "n": n, "threshold_q": threshold_q,
    }


def threshold_stability(losses, alpha: float = 0.99, qs=None) -> list[dict]:
    qs = np.round(np.arange(0.85, 0.971, 0.01), 2) if qs is None else qs
    out = []
    for q in qs:
        try:
            r = var_es_evt(losses, alpha, float(q))
            out.append({"threshold_q": float(q), "xi": r["xi"], "var": r["var"], "n_u": r["n_u"]})
        except ValueError:
            continue
    return out
