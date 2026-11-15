"""Holdings -> HKD positions -> hypothetical P&L for the current book."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from hkrisk import PROJECT_ROOT
from hkrisk.data import align_prices

PORTFOLIO_PATH = PROJECT_ROOT / "portfolio.yaml"


def load_portfolio(path: Path | str | None = None) -> dict[str, float]:
    with open(path or PORTFOLIO_PATH) as f:
        cfg = yaml.safe_load(f)
    return {str(k): float(v) for k, v in cfg["holdings"].items()}


def simple_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """R_t = P_t / P_{t-1} - 1 (first row dropped)."""
    return prices.pct_change(fill_method=None).iloc[1:]


def _upto(df: pd.DataFrame, as_of) -> pd.DataFrame:
    if as_of is None:
        return df
    return df.loc[: pd.Timestamp(as_of)]


def position_values(holdings: dict[str, float], prices: pd.DataFrame, as_of=None) -> pd.Series:
    """HKD value of each position at the last available date <= as_of."""
    px = align_prices(_upto(prices, as_of), list(holdings))
    if px.empty:
        raise ValueError(f"no prices on or before {as_of}")
    last = px.iloc[-1]
    vals = pd.Series({t: holdings[t] * last[t] for t in holdings}, name="value_hkd")
    vals.attrs["as_of"] = px.index[-1]
    return vals


def returns_window(
    holdings: dict[str, float], prices: pd.DataFrame, as_of=None, window: int = 500
) -> pd.DataFrame:
    """Last ``window`` days of simple returns (<= as_of) for the held tickers."""
    px = align_prices(_upto(prices, as_of), list(holdings))
    rets = simple_returns(px)
    if len(rets) < window:
        raise ValueError(f"only {len(rets)} return days before {as_of}, need {window}")
    return rets.iloc[-window:]


def hypothetical_pnl(
    holdings: dict[str, float], prices: pd.DataFrame, as_of=None, window: int = 500
) -> pd.Series:
    """Today's positions x each historical day's returns: PnL_t = sum_i V_i,as_of * R_i,t."""
    vals = position_values(holdings, prices, as_of)
    rets = returns_window(holdings, prices, as_of, window)
    pnl = rets[vals.index] @ vals.values
    pnl.name = "pnl_hkd"
    return pnl


def portfolio_value(holdings, prices, as_of=None) -> float:
    return float(np.sum(position_values(holdings, prices, as_of)))
