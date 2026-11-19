"""Pre-compute every API response the dashboard can ask for, so it can be hosted as static
files (GitHub Pages) with no backend. Output: dashboard/public/static-data/<key>.json.

The key is the request path + query with every character outside [A-Za-z0-9._-] replaced by
"_" (dashboard/src/api.ts `staticKey` does the same). Offline: uses the committed snapshots.

    uv run python scripts/export_static.py
"""
import glob
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

os.environ["HKRISK_IP_RATE_LIMIT_PER_MIN"] = "1000000"  # local export, not a public endpoint
os.environ.pop("HKRISK_TRUST_PROXY", None)

from fastapi.testclient import TestClient

from hkrisk.api.main import app

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "dashboard" / "public" / "static-data"
PORTFOLIOS = ["core", "hsi"]
METHODS = ["historical", "normal", "t", "garch", "evt"]
ALPHAS = [0.95, 0.975, 0.99]
SHOCKS = range(-50, 31)  # the dashboard slider: -50..+30 percent
EXAMPLE_IDS = ["a03", "a02", "c04", "s04", "b01", "r04"]  # recorded agent answers (core book)


def key(path_and_query: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", path_and_query).lstrip("_")


def num(x: float) -> str:  # same text as JavaScript's String(number) for these values
    return "0" if x == 0 else repr(x)


def qs(**kw) -> str:
    return "?" + "&".join(f"{k}={v}" for k, v in kw.items())


def round_series(d: dict) -> dict:
    d["var"] = [round(v, 2) for v in d["var"]]
    d["loss"] = [round(v, 2) for v in d["loss"]]
    return d


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for f in OUT.glob("*.json"):
        f.unlink()
    n = 0
    t0 = time.time()
    with TestClient(app) as c:
        def grab(path: str, post_fn=None):
            nonlocal n
            r = c.get(path)
            if r.status_code != 200:
                sys.exit(f"{path} -> {r.status_code} {r.text[:200]}")
            data = r.json()
            if post_fn:
                data = post_fn(data)
            (OUT / f"{key(path)}.json").write_text(json.dumps(data, separators=(",", ":")))
            n += 1
            return data

        for pf in PORTFOLIOS:
            grab("/portfolio" + qs(portfolio=pf))
            scen = grab("/stress/scenarios")["scenarios"]  # the dashboard sends no portfolio here
            for s in scen:
                grab("/stress/" + quote(s["name"], safe="-_.!~*'()") + qs(portfolio=pf))
            for pct in SHOCKS:
                grab("/stress/hsi-shock" + qs(portfolio=pf, shock=num(pct / 100)))
            for a in ALPHAS:
                grab("/risk/compare" + qs(portfolio=pf, alpha=a))
                grab("/risk/explain-change" + qs(portfolio=pf, alpha=a))
                for m in ("historical", "normal"):
                    grab("/risk/contributions" + qs(portfolio=pf, method=m, alpha=a))
                for m in METHODS:
                    grab("/risk/var" + qs(portfolio=pf, method=m, alpha=a))
                    grab("/backtest" + qs(portfolio=pf, method=m, alpha=a))
                    grab("/backtest/series" + qs(portfolio=pf, method=m, alpha=a), round_series)
            print(f"{pf}: done, {n} files, {time.time() - t0:.0f}s", flush=True)

    # recorded agent answers from the committed eval runs (real model output, core book)
    found: dict[str, dict] = {}
    for f in sorted(glob.glob(str(ROOT / "evals" / "results" / "*.json"))):
        for r in json.loads(Path(f).read_text())["rows"]:
            if r["id"] in EXAMPLE_IDS and r.get("passed") is True and r["id"] not in found:
                found[r["id"]] = {
                    "question": r["question"], "answer": r["answer"], "tool_calls": r["tool_calls"],
                    "iterations": r["iterations"], "input_tokens": r["input_tokens"],
                    "output_tokens": r["output_tokens"], "latency_s": r["latency_s"],
                    "provider": r["provider"], "model": r["model"],
                }
    examples = [found[i] for i in EXAMPLE_IDS if i in found]
    (OUT / "agent_examples.json").write_text(json.dumps(examples, separators=(",", ":")))
    size = sum(p.stat().st_size for p in OUT.glob("*.json")) / 1e6
    print(f"wrote {n} responses + {len(examples)} agent examples, {size:.1f} MB -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
