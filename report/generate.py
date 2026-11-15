"""Generate the daily report locally.

    uv run python report/generate.py              # refresh prices from Yahoo, write reports/<date>/
    uv run python report/generate.py --no-refresh # use the snapshot/cache only (offline)
"""

import argparse
from pathlib import Path

from hkrisk.report import run_local

ap = argparse.ArgumentParser()
ap.add_argument("--out", default="reports")
ap.add_argument("--no-refresh", action="store_true")
a = ap.parse_args()
print(run_local(Path(a.out), refresh=not a.no_refresh))
