"""Historical and hypothetical stress scenarios applied to today's positions."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from hkrisk import PROJECT_ROOT
from hkrisk.portfolio import position_values

SCENARIOS_PATH = PROJECT_ROOT / "scenarios.yaml"
INDEX = "^HSI"


def find_drawdown_window(index_prices: pd.Series, start, end) -> dict:
    """Largest peak-to-trough drawdown of the index inside [start, end]."""
    s = index_prices.loc[pd.Timestamp(start): pd.Timestamp(end)].dropna()
    dd = s / s.cummax() - 1
    trough = dd.idxmin()
    peak = s.loc[:trough].idxmax()
    return {"peak": peak.strftime("%Y-%m-%d"), "trough": trough.strftime("%Y-%m-%d"),
            "drawdown": float(s[trough] / s[peak] - 1),
            "trading_days": int(len(s.loc[peak:trough]) - 1)}


def load_scenarios(path: Path | str | None = None) -> dict:
    with open(path or SCENARIOS_PATH) as f:
        return yaml.safe_load(f)["scenarios"]


def hsi_beta(prices: pd.DataFrame, ticker: str, as_of=None, index: str = INDEX) -> float:
    """OLS beta of the ticker's daily simple returns on ^HSI, all data up to as_of."""
    px = prices.loc[: pd.Timestamp(as_of)] if as_of else prices
    df = px[[ticker, index]].dropna().pct_change(fill_method=None).dropna()
    if len(df) < 60:
        raise ValueError(f"not enough history to estimate beta for {ticker}")
    x, y = df[index].to_numpy(), df[ticker].to_numpy()
    return float(np.cov(x, y, ddof=1)[0, 1] / np.var(x, ddof=1))


def _price_on(s: pd.Series, date) -> float | None:
    """Last available close on or before date, but only if the series existed by then."""
    s = s.dropna()
    if s.empty or s.index[0] > pd.Timestamp(date):
        return None
    return float(s.loc[: pd.Timestamp(date)].iloc[-1])


def run_historical_scenario(holdings, prices, scenario: dict | str, as_of=None) -> dict:
    if isinstance(scenario, str):
        name = scenario
        scenario = load_scenarios()[scenario]
    else:
        name = scenario.get("name", "custom")
    start, end = scenario["start"], scenario["end"]
    vals = position_values(holdings, prices, as_of)
    idx_shock = _price_on(prices[INDEX], end) / _price_on(prices[INDEX], start) - 1
    rows, proxied = [], []
    for t, v in vals.items():
        p0, p1 = _price_on(prices[t], start), _price_on(prices[t], end)
        if p0 is not None and p1 is not None:
            shock, beta, is_proxy = p1 / p0 - 1, None, False
        else:
            beta = hsi_beta(prices, t, as_of)
            shock, is_proxy = beta * idx_shock, True
            proxied.append(t)
        rows.append({"ticker": t, "position_value": float(v), "shock": float(shock),
                     "pnl": float(v * shock), "proxied": is_proxy, "beta": beta})
    total = sum(r["pnl"] for r in rows)
    value = float(vals.sum())
    return {
        "scenario": name, "description": scenario.get("description", ""),
        "start": start, "end": end, "hsi_shock": float(idx_shock),
        "as_of": vals.attrs["as_of"].strftime("%Y-%m-%d"), "currency": "HKD",
        "portfolio_value": value, "total_pnl": float(total), "total_pnl_pct": float(total / value),
        "positions": sorted(rows, key=lambda r: r["pnl"]), "proxied": proxied,
    }


def run_hsi_shock(holdings, prices, shock: float, as_of=None) -> dict:
    """Hypothetical: every name moves by beta_i * shock (beta vs ^HSI, data up to as_of)."""
    vals = position_values(holdings, prices, as_of)
    rows = []
    for t, v in vals.items():
        b = hsi_beta(prices, t, as_of)
        rows.append({"ticker": t, "position_value": float(v), "beta": b, "shock": b * shock,
                     "pnl": float(v * b * shock)})
    total = sum(r["pnl"] for r in rows)
    value = float(vals.sum())
    return {"scenario": f"HSI {shock:+.0%}", "hsi_shock": shock,
            "as_of": vals.attrs["as_of"].strftime("%Y-%m-%d"), "currency": "HKD",
            "portfolio_value": value, "total_pnl": float(total),
            "total_pnl_pct": float(total / value),
            "positions": sorted(rows, key=lambda r: r["pnl"])}
