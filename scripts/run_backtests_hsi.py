"""Backtest table for the 95-name Hang Seng Index book.

    uv run python scripts/run_backtests_hsi.py

Writes docs/backtest_results_hsi.{json,md}. Test days start where >= 90% of the book's weight
has real price history (see RiskService.load); earlier returns of late listings are
beta x HSI proxies.
"""

import json

from hkrisk import PROJECT_ROOT
from hkrisk.risk import METHODS
from hkrisk.service import RiskService

DOCS = PROJECT_ROOT / "docs"
svc = RiskService.load("hsi")
res = {m: svc.backtest(m) for m in METHODS}
r0 = res["historical"]
lines = [
    "# Backtest: Hang Seng Index book (95 names, index-weighted, HKD 10m)", "",
    (f"{r0['start']} to {r0['end']} ({r0['days']} days, {r0['years']} years), 99% 1-day VaR, "
     f"500-day window. {len(svc.repairs['beta_backfilled'])} late listings use beta x HSI "
     "returns before their first real price."), "",
    ("| Model | Exceptions (exp.) | Kupiec p | Christoffersen ind. p | Cond. cov. p "
     "| Rolling 250d windows G / Y / R |"),
    "|---|---|---|---|---|---|",
]
for m, r in res.items():
    z = r["rolling_zone_days"]
    lines.append(f"| {m} | {r['exceptions']} ({r['expected']:.1f}) | {r['kupiec_p']:.3f} | "
                 f"{r['christoffersen_ind_p']:.3f} | {r['christoffersen_cc_p']:.3f} | "
                 f"{z['green']} / {z['yellow']} / {z['red']} |")
(DOCS / "backtest_results_hsi.md").write_text("\n".join(lines) + "\n")
(DOCS / "backtest_results_hsi.json").write_text(json.dumps(res, indent=2))
print("\n".join(lines))
