"""Thin, JSON-safe facade over the engine. Used by the API, the agent tools and the report.

Holds prices + holdings in memory. No maths here: every number comes from engine modules.
"""

from __future__ import annotations

import math
import os
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from hkrisk import PROJECT_ROOT, attribution, backtest, proxy, stress
from hkrisk.data import SNAPSHOT_PATH
from hkrisk.portfolio import PORTFOLIO_PATH, load_portfolio, position_values
from hkrisk.risk import DEFAULT_WINDOW, METHODS, compute_risk
from hkrisk.universe import HSI_SNAPSHOT_PATH, names, sectors


def jsonable(x):
    """Recursively convert numpy/pandas scalars to Python and NaN/inf to None."""
    if isinstance(x, dict):
        return {str(k): jsonable(v) for k, v in x.items() if not str(k).startswith("_")}
    if isinstance(x, (list, tuple)):
        return [jsonable(v) for v in x]
    if isinstance(x, (np.bool_, bool)):
        return bool(x)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        x = float(x)
        return None if math.isnan(x) or math.isinf(x) else x
    if isinstance(x, pd.Timestamp):
        return x.strftime("%Y-%m-%d")
    return x


# Named books. "core" (9 names) is the frozen reference for tests, the R check and the eval;
# "hsi" holds every Hang Seng Index constituent at its official index weight.
PORTFOLIOS = {
    "core": {"label": "Core 9", "holdings": PORTFOLIO_PATH, "prices": SNAPSHOT_PATH,
             "env_prices": "HKRISK_PRICES", "env_holdings": "HKRISK_PORTFOLIO", "repair": False},
    "hsi": {"label": "Hang Seng Index (95)", "holdings": PROJECT_ROOT / "portfolios" / "hsi.yaml",
            "prices": HSI_SNAPSHOT_PATH, "env_prices": "HKRISK_PRICES_HSI",
            "env_holdings": "HKRISK_PORTFOLIO_HSI", "repair": True},
}


def _read_prices(src: str, fallback: Path) -> pd.DataFrame:
    if src.startswith("s3://"):  # Lambda: daily-refreshed cache written by the report job
        import boto3

        bucket, key = src[5:].split("/", 1)
        local = Path("/tmp") / Path(key).name
        try:
            boto3.client("s3").download_file(bucket, key, str(local))
            src = str(local)
        except Exception:  # noqa: BLE001  fall back to the snapshot baked into the image
            src = str(fallback)
    return pd.read_parquet(Path(src))


class RiskService:
    def __init__(self, prices: pd.DataFrame, holdings: dict[str, float], *,
                 raw_prices: pd.DataFrame | None = None, name: str = "core",
                 label: str = "Core 9", repairs: dict | None = None):
        self.prices = prices                      # used for VaR / ES / backtests
        self.raw_prices = raw_prices if raw_prices is not None else prices  # stress tests
        self.holdings = holdings
        self.name, self.label = name, label
        self.repairs = repairs or {}
        self.backtest_start: str | None = None  # earliest test day for "full history"
        self.latest = prices.dropna(subset=list(holdings)).index[-1].strftime("%Y-%m-%d")
        self._bt_cache: dict = {}

    @classmethod
    def load(cls, name: str = "core") -> RiskService:
        if name not in PORTFOLIOS:
            raise ValueError(f"unknown portfolio {name!r}; choose from {sorted(PORTFOLIOS)}")
        cfg = PORTFOLIOS[name]
        raw = _read_prices(os.getenv(cfg["env_prices"], str(cfg["prices"])), cfg["prices"])
        holdings = load_portfolio(os.getenv(cfg["env_holdings"], cfg["holdings"]))
        missing = [t for t in holdings if t not in raw.columns]
        if missing:
            raise ValueError(f"no price history for {missing}")
        if not cfg["repair"]:
            return cls(raw, holdings, name=name, label=cfg["label"])
        cleaned, dropped = proxy.drop_stale_prefix(raw)
        filled, backfilled = proxy.beta_backfill(cleaned)
        held = {t: v for t, v in backfilled.items() if t in holdings}
        svc = cls(filled, holdings, raw_prices=cleaned, name=name, label=cfg["label"],
                  repairs={"stale_prefix_dropped": dropped, "beta_backfilled": held})
        # Backtest test days only where >= 90% of the book (by today's value) has real
        # prices, so the backtest is not mostly scoring synthetic beta-proxied history.
        vals = position_values(holdings, filled, svc.latest)
        w = vals / vals.sum()
        first = sorted((pd.Timestamp(v["first_real_date"]), t) for t, v in held.items())
        proxied_w = sum(w[t] for _, t in first)
        start = None
        for d, t in first:
            if proxied_w <= 0.10:
                break
            proxied_w -= w[t]
            start = d
        svc.backtest_start = start.strftime("%Y-%m-%d") if start is not None else None
        return svc

    @classmethod
    def from_env(cls) -> RiskService:
        return cls.load("core")

    def _as_of(self, as_of):
        if as_of is None:
            return self.latest
        ts = pd.Timestamp(as_of)
        if ts > pd.Timestamp(self.latest):
            raise ValueError(f"as_of {as_of} is after the latest data date {self.latest}")
        if ts < self.prices.index[0]:
            raise ValueError(f"as_of {as_of} is before the first data date")
        return ts.strftime("%Y-%m-%d")

    # ---- portfolio
    def portfolio(self, as_of=None) -> dict:
        as_of = self._as_of(as_of)
        v = position_values(self.holdings, self.prices, as_of)
        total = float(v.sum())
        px = self.prices.loc[: pd.Timestamp(as_of), list(self.holdings)].ffill().iloc[-1]
        nm, sec = names(), sectors()
        backfilled = self.repairs.get("beta_backfilled", {})
        return jsonable({
            "portfolio": self.name, "label": self.label,
            "as_of": v.attrs["as_of"], "currency": "HKD", "total_value": total,
            "n_positions": len(self.holdings),
            "positions": [{"ticker": t, "name": nm.get(t, t), "sector": sec.get(t),
                           "shares": self.holdings[t], "price": float(px[t]),
                           "value": float(v[t]), "weight": float(v[t] / total),
                           "history_proxied_before": backfilled.get(t, {}).get("first_real_date")}
                          for t in v.sort_values(ascending=False).index],
        })

    # ---- risk
    def var(self, method="historical", alpha=0.99, window=DEFAULT_WINDOW, as_of=None,
            horizon_days=1) -> dict:
        return jsonable(compute_risk(self.holdings, self.prices, self._as_of(as_of), method,
                                     alpha, window, horizon_days))

    def compare_methods(self, alpha=0.99, window=DEFAULT_WINDOW, as_of=None) -> dict:
        as_of = self._as_of(as_of)
        rows = [self.var(m, alpha, window, as_of) for m in METHODS]
        rows.sort(key=lambda r: r["var"], reverse=True)
        return {"as_of": rows[0]["as_of"], "alpha": alpha, "window": window, "currency": "HKD",
                "portfolio_value": rows[0]["portfolio_value"],
                "ranked_by_var_desc": [{k: r.get(k) for k in
                                        ("method", "var", "es", "var_pct", "es_pct")}
                                       for r in rows],
                "highest_var_method": rows[0]["method"], "lowest_var_method": rows[-1]["method"]}

    def contributions(self, method="historical", measure="var", alpha=0.99,
                      window=DEFAULT_WINDOW, as_of=None) -> dict:
        return jsonable(attribution.contributions(self.holdings, self.prices, self._as_of(as_of),
                                                  method, measure, alpha, window))

    def explain_change(self, start_date=None, end_date=None, method="historical", alpha=0.99,
                       window=DEFAULT_WINDOW) -> dict:
        end = self._as_of(end_date)
        return jsonable(attribution.explain_change(self.holdings, self.prices, start_date, end,
                                                   method, alpha, window))

    # ---- stress
    def scenarios(self) -> dict:
        sc = stress.load_scenarios()
        return {"scenarios": [{"name": k, "start": v["start"], "end": v["end"],
                               "description": v["description"],
                               "hsi_drawdown": v["hsi_drawdown"]} for k, v in sc.items()],
                "also_available": "hypothetical HSI shock of any size (run_hsi_shock)"}

    def stress(self, scenario: str, as_of=None) -> dict:
        sc = stress.load_scenarios()
        if scenario not in sc:
            raise ValueError(f"unknown scenario {scenario!r}; choose from {sorted(sc)}")
        return jsonable(stress.run_historical_scenario(self.holdings, self.raw_prices, scenario,
                                                       self._as_of(as_of)))

    def hsi_shock(self, shock: float, as_of=None) -> dict:
        if not -0.9 <= shock <= 0.9:
            raise ValueError("shock must be a decimal between -0.9 and 0.9, e.g. -0.2 for -20%")
        return jsonable(stress.run_hsi_shock(self.holdings, self.raw_prices, shock,
                                             self._as_of(as_of)))

    # ---- backtest
    def _backtest_df(self, method, years, alpha, window, as_of) -> pd.DataFrame:
        key = ("df", method, years, alpha, window, as_of)
        if key not in self._bt_cache:
            # years=None: the full history the data allows (first day with `window` days of
            # returns for every holding); this is the period quoted in the README
            start = (pd.Timestamp(self.backtest_start) if self.backtest_start else None)
            if years is not None:
                start = pd.Timestamp(as_of) - pd.DateOffset(days=round(years * 365.25))
            df = backtest.rolling_var(self.holdings, self.prices, method, alpha, window,
                                      start=start, end=as_of)
            if len(df) < 250:
                raise ValueError(f"only {len(df)} test days available; need >= 250. "
                                 "Use fewer years or a shorter window.")
            self._bt_cache[key] = df
        return self._bt_cache[key]

    def backtest_series(self, method="historical", years: float | None = None, alpha=0.99,
                        window=DEFAULT_WINDOW, as_of=None) -> dict:
        """Daily out-of-sample VaR forecast vs realised loss (for charts)."""
        as_of = self._as_of(as_of)
        df = self._backtest_df(method, years, alpha, window, as_of)
        return jsonable({"method": method, "alpha": alpha, "window": window, "as_of": as_of,
                         "currency": "HKD",
                         "dates": [d.strftime("%Y-%m-%d") for d in df.index],
                         "var": df["var"].round(2).tolist(),
                         "loss": df["loss"].round(2).tolist(),
                         "exception": df["exception"].astype(bool).tolist()})

    def backtest(self, method="historical", years: float | None = None, alpha=0.99,
                 window=DEFAULT_WINDOW, as_of=None) -> dict:
        as_of = self._as_of(as_of)
        key = (method, years, alpha, window, as_of)
        if key not in self._bt_cache:
            df = self._backtest_df(method, years, alpha, window, as_of)
            s = backtest.summarize(df, alpha)
            s.update(method=method, alpha=alpha, window=window, as_of=as_of, currency="HKD",
                     requested_years=years,
                     kupiec_pass=not s["kupiec_reject"], christoffersen_cc_pass=not s["cc_reject"])
            self._bt_cache[key] = jsonable(s)
        return self._bt_cache[key]


@lru_cache(maxsize=len(PORTFOLIOS))
def get_service(name: str = "core") -> RiskService:
    return RiskService.load(name)
