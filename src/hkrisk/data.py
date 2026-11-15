"""Price download and on-disk Parquet cache.

Missing-value policy (see README "Conventions"):
- Cached/snapshot files keep per-ticker NaNs (late listings stay NaN before listing).
- ``align_prices`` is applied at use time: forward-fill at most ONE day (holiday /
  suspension mismatch), then drop dates where any requested ticker is still NaN.
  ffill only uses past values, so it introduces no look-ahead.
"""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path

import pandas as pd

from hkrisk import PROJECT_ROOT

log = logging.getLogger(__name__)

DATA_DIR = PROJECT_ROOT / "data"
SNAPSHOT_AS_OF = "2026-10-30"
SNAPSHOT_PATH = DATA_DIR / f"snapshot_{SNAPSHOT_AS_OF}.parquet"
FIXTURE_PATH = PROJECT_ROOT / "tests" / "fixtures" / "prices_small.parquet"


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    df.index.name = "date"
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df.dropna(how="all", axis=1).dropna(how="all", axis=0)
    df.columns.name = None
    return df.astype(float)


def download_prices(
    tickers: list[str], start: str, end: str, retries: int = 3
) -> pd.DataFrame:
    """Download adjusted closes from Yahoo (network). ``end`` is inclusive."""
    import yfinance as yf

    end_excl = (pd.Timestamp(end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    out: dict[str, pd.Series] = {}
    for t in tickers:  # one at a time: yfinance's threaded mode hits sqlite locks
        for attempt in range(retries):
            try:
                raw = yf.download(
                    t, start=start, end=end_excl, auto_adjust=True,
                    progress=False, threads=False,
                )
                close = raw["Close"]
                if isinstance(close, pd.DataFrame):
                    close = close.iloc[:, 0]
                if close.dropna().empty:
                    raise ValueError(f"no data for {t}")
                out[t] = close
                break
            except Exception as exc:  # noqa: BLE001
                log.warning("download %s attempt %d failed: %s", t, attempt + 1, exc)
                time.sleep(2 * (attempt + 1))
        else:
            raise RuntimeError(f"failed to download {t} after {retries} attempts")
    return _clean(pd.DataFrame(out))


def _cache_path(tickers: list[str], start: str, end: str) -> Path:
    key = hashlib.sha1(f"{sorted(tickers)}|{start}|{end}".encode()).hexdigest()[:12]
    return DATA_DIR / f"prices_{key}.parquet"


def load_prices(
    tickers: list[str], start: str, end: str, refresh: bool = False
) -> pd.DataFrame:
    """Read prices from the Parquet cache; download only if missing or refresh=True."""
    path = _cache_path(tickers, start, end)
    if path.exists() and not refresh:
        return pd.read_parquet(path)
    df = download_prices(tickers, start, end)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)
    return df


def load_snapshot(path: Path | str | None = None) -> pd.DataFrame:
    """The frozen, committed price history used by backtests, stress tests and evals."""
    return pd.read_parquet(path or SNAPSHOT_PATH)


def align_prices(prices: pd.DataFrame, tickers: list[str] | None = None) -> pd.DataFrame:
    """Select tickers, forward-fill at most one day, drop rows still containing NaN."""
    df = prices if tickers is None else prices[list(tickers)]
    return df.ffill(limit=1).dropna(how="any")
