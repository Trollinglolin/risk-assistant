"""Export the SAME inputs the Python engine uses, for the R cross-check (Step 8).

    uv run python scripts/export_reference_input.py && Rscript reference/validate_reference.R
"""

import pandas as pd

from hkrisk import PROJECT_ROOT
from hkrisk.data import load_snapshot
from hkrisk.portfolio import hypothetical_pnl, load_portfolio, portfolio_value

REF = PROJECT_ROOT / "reference"
prices, holdings = load_snapshot(), load_portfolio()
pnl = hypothetical_pnl(holdings, prices, None, 500)
value = portfolio_value(holdings, prices)
pd.DataFrame({"date": pnl.index.strftime("%Y-%m-%d"), "pnl": pnl.values,
              "ret": pnl.values / value}).to_csv(REF / "input.csv", index=False, float_format="%.17g")
bt = pd.read_parquet(PROJECT_ROOT / "docs" / "backtest_historical.parquet")
pd.DataFrame({"date": bt.index.strftime("%Y-%m-%d"),
              "exception": bt["exception"].astype(int)}).to_csv(REF / "exceptions.csv", index=False)
(REF / "value.txt").write_text(repr(value) + "\n")
print("wrote", REF / "input.csv", len(pnl), "rows; value", value)
