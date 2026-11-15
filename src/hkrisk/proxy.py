"""Price-history repairs for a wide universe (used by the HSI portfolio, not the core book).

Two problems appear once the book holds every HSI constituent:

1. **Reused stock codes.** HKEX recycles codes, and Yahoo sometimes keeps a stray price from
   the previous holder (0300.HK has one 2024-07 print, then nothing until Midea's H-share
   listing). ``drop_stale_prefix`` discards observations that sit before a long gap.
2. **Short histories.** CATL listed in 2025, so requiring every name on every day would leave
   no 500-day window. ``beta_backfill`` extends each late listing backwards with
   ``r_t = beta * r_HSI,t``, beta estimated by OLS on the stock's first ``beta_obs`` real
   returns. This is the same beta proxy the stress tests use for unlisted names.

   Caveat (also in the README): proxied days carry index risk only, no idiosyncratic risk, so
   VaR for windows dominated by proxied days is understated for those names.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

INDEX = "^HSI"


def drop_stale_prefix(prices: pd.DataFrame, max_gap: int = 20) -> tuple[pd.DataFrame, dict]:
    """Blank out each ticker's observations before its last gap of > ``max_gap`` rows."""
    out, dropped = prices.copy(), {}
    for t in prices.columns:
        s = prices[t]
        valid = np.flatnonzero(s.notna().to_numpy())
        if len(valid) < 2:
            continue
        jumps = np.flatnonzero(np.diff(valid) > max_gap)
        if len(jumps):
            cut = valid[jumps[-1] + 1]
            dropped[t] = int(s.iloc[:cut].notna().sum())
            out.iloc[:cut, out.columns.get_loc(t)] = np.nan
    return out, dropped


def beta_backfill(prices: pd.DataFrame, index: str = INDEX, beta_obs: int = 250,
                  min_obs: int = 60) -> tuple[pd.DataFrame, dict]:
    """Extend late listings back to the index's first date using beta x index returns.

    Returns (filled prices, {ticker: {"first_real_date", "beta", "beta_obs"}}).
    Prices on and after each ticker's first real observation are untouched.
    """
    idx = prices[index].ffill(limit=1)
    idx_ret = idx.pct_change(fill_method=None).fillna(0.0)
    start = idx.first_valid_index()
    out, info = prices.copy(), {}
    for t in prices.columns:
        if t == index:
            continue
        s = prices[t]
        first = s.first_valid_index()
        if first is None or first <= start:
            continue
        real = s.loc[first:].ffill(limit=1).pct_change(fill_method=None)
        joint = pd.concat([real, idx_ret], axis=1, keys=["s", "m"], sort=True).dropna().iloc[:beta_obs]
        if len(joint) >= min_obs and joint["m"].var() > 0:
            beta = float(np.cov(joint["s"], joint["m"], ddof=1)[0, 1] / joint["m"].var(ddof=1))
        else:
            beta = 1.0
        # walk backwards from the first real price: P_{d-1} = P_d / (1 + beta * r_m,d)
        pre = prices.index[(prices.index >= start) & (prices.index <= first)]
        vals = np.empty(len(pre))
        vals[-1] = float(s.loc[first])
        growth = 1.0 + beta * idx_ret.loc[pre].to_numpy()
        for k in range(len(pre) - 1, 0, -1):
            vals[k - 1] = vals[k] / growth[k]
        out.loc[pre[:-1], t] = vals[:-1]
        info[t] = {"first_real_date": first.strftime("%Y-%m-%d"), "beta": beta,
                   "beta_obs": len(joint)}
    return out, info
