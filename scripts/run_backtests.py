"""Rolling out-of-sample backtest of every VaR model on the frozen snapshot.

    uv run python scripts/run_backtests.py

Writes docs/backtest_results.{json,md}, docs/backtest_<method>.parquet and charts.
"""

import json
import time

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from hkrisk import PROJECT_ROOT
from hkrisk.backtest import rolling_var, summarize
from hkrisk.data import load_snapshot
from hkrisk.evt import threshold_stability
from hkrisk.portfolio import hypothetical_pnl, load_portfolio
from hkrisk.risk import METHODS
from hkrisk.var_models import fit_garch

DOCS = PROJECT_ROOT / "docs"
DOCS.mkdir(exist_ok=True)
ALPHA, WINDOW = 0.99, 500

prices, holdings = load_snapshot(), load_portfolio()
results, frames = {}, {}
for m in METHODS:
    t0 = time.time()
    df = rolling_var(holdings, prices, m, ALPHA, WINDOW)
    df.to_parquet(DOCS / f"backtest_{m}.parquet")
    frames[m] = df
    results[m] = summarize(df, ALPHA)
    print(f"{m:10s} {time.time() - t0:6.1f}s  {results[m]['exceptions']} exc  "
          f"kupiec p={results[m]['kupiec_p']:.3f}  zones={results[m]['rolling_zone_days']}")

(DOCS / "backtest_results.json").write_text(json.dumps(results, indent=2, default=str))

r0 = next(iter(results.values()))
lines = [
    (f"Backtest: 99% 1-day VaR, {WINDOW}-day window, fixed current share counts, "
    f"{r0['start']} to {r0['end']} ({r0['days']} days, {r0['years']} years, "
    f"expected exceptions {r0['expected']})."),
    "",
    ("| Model | Exceptions | Kupiec p | Christoffersen ind p | Cond. coverage p "
    "| Latest 250d zone | Rolling 250d windows G / Y / R | Worst 250d count |"),
    "|---|---|---|---|---|---|---|---|",
]
for m, r in results.items():
    z = r["rolling_zone_days"]
    lines.append(
        f"| {m} | {r['exceptions']} | {r['kupiec_p']:.3f} | {r['christoffersen_ind_p']:.3f} "
        f"| {r['christoffersen_cc_p']:.3f} | {r['latest_250d']['zone']} "
        f"({r['latest_250d']['count']}) | {z['green']} / {z['yellow']} / {z['red']} "
        f"| {r['worst_250d_count']} |")
(DOCS / "backtest_results.md").write_text("\n".join(lines) + "\n")
print("\n".join(lines))

# --- chart: losses vs VaR lines, exceptions marked
fig, ax = plt.subplots(figsize=(13, 5.5))
loss = frames["historical"]["loss"]
ax.plot(loss.index, loss / 1e3, color="#9aa0a6", lw=0.6, label="realised loss")
colors = {"historical": "#1f77b4", "normal": "#d62728", "t": "#9467bd",
          "garch": "#2ca02c", "evt": "#ff7f0e"}
for m, df in frames.items():
    ax.plot(df.index, df["var"] / 1e3, lw=1, color=colors[m], label=f"{m} VaR")
for m in ("historical", "garch"):
    e = frames[m][frames[m]["exception"]]
    ax.scatter(e.index, e["loss"] / 1e3, color=colors[m], edgecolor="red", s=22, zorder=5,
               label=f"{m} exceptions ({len(e)})")
ax.set_ylabel("HKD thousands (loss positive)")
ax.set_title("99% 1-day VaR backtest, current HK portfolio")
ax.legend(ncol=4, fontsize=8, loc="upper left")
fig.tight_layout()
fig.savefig(DOCS / "backtest_chart.png", dpi=130)

# --- GARCH conditional vol on the long-history Tracker Fund (2800.HK) -> 2008, 2020, 2022
r = prices["2800.HK"].dropna().pct_change().dropna()
res = fit_garch(r.values)
fig, ax = plt.subplots(figsize=(13, 4))
ax.plot(r.index, np.asarray(res.conditional_volatility) / 100 * np.sqrt(252), lw=0.8)
ax.set_title("GARCH(1,1)-t conditional volatility, 2800.HK (annualised)")
fig.tight_layout()
fig.savefig(DOCS / "garch_sigma.png", dpi=130)

# --- EVT threshold stability for the current book
pnl = hypothetical_pnl(holdings, prices, None, 1500)
stab = threshold_stability(-pnl.values, 0.99)
fig, ax1 = plt.subplots(figsize=(8, 4))
q = [s["threshold_q"] for s in stab]
ax1.plot(q, [s["xi"] for s in stab], "o-", label="xi")
ax1.set_xlabel("threshold quantile")
ax1.set_ylabel("xi")
ax2 = ax1.twinx()
ax2.plot(q, [s["var"] / 1e3 for s in stab], "s--", color="C1", label="99% VaR (HKD k)")
ax2.set_ylabel("99% VaR, HKD thousands")
ax1.set_title("EVT threshold stability (1500-day window)")
fig.tight_layout()
fig.savefig(DOCS / "evt_threshold_stability.png", dpi=130)
print(json.dumps(stab, indent=1))
