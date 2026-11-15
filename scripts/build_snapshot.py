"""Build the frozen snapshot and the small test fixture (needs network, run once).

    uv run python scripts/build_snapshot.py
"""

from hkrisk.data import FIXTURE_PATH, SNAPSHOT_AS_OF, SNAPSHOT_PATH, download_prices
from hkrisk.portfolio import load_portfolio

tickers = list(load_portfolio()) + ["^HSI"]
df = download_prices(tickers, "2007-01-01", SNAPSHOT_AS_OF)
SNAPSHOT_PATH.parent.mkdir(exist_ok=True)
df.to_parquet(SNAPSHOT_PATH)
print(SNAPSHOT_PATH, df.shape, df.index.min().date(), df.index.max().date())
print(df.apply(lambda s: s.first_valid_index().date()))

small = df.loc["2025-10-01":SNAPSHOT_AS_OF]
FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
small.to_parquet(FIXTURE_PATH)
print(FIXTURE_PATH, small.shape)
