"""Daily risk report: refresh prices, compute everything, write report.json + report.html.

Local:  uv run python report/generate.py --out reports/
Lambda: handler() -> writes to s3://$REPORT_BUCKET/reports/<date>/ and keeps the price
        cache at s3://$REPORT_BUCKET/data/prices_live.parquet.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from jinja2 import Template

from hkrisk.backtest import rolling_var, summarize, traffic_light
from hkrisk.data import download_prices, load_snapshot
from hkrisk.portfolio import load_portfolio
from hkrisk.risk import METHODS
from hkrisk.service import RiskService, jsonable

log = logging.getLogger(__name__)


def refresh_prices(cache: pd.DataFrame, tickers: list[str]) -> tuple[pd.DataFrame, bool]:
    """Re-download FULL history (adjusted closes change retroactively after every dividend,
    so splicing a short download onto an old cache would create fake jumps at the seam).
    Returns (prices, stale). Never raises on network errors; falls back to the cache."""
    start = cache.index[0].strftime("%Y-%m-%d")
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    try:
        new = download_prices(tickers, start, today)
    except Exception as e:  # noqa: BLE001
        log.warning("price refresh failed, using cache: %s", e)
        return cache, True
    if new.index[-1] < cache.index[-1] or len(new) < 0.95 * len(cache):
        log.warning("refresh returned less history than the cache; keeping cache")
        return cache, True
    return new, False


def _png(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    return base64.b64encode(buf.getvalue()).decode()


def build_report(prices: pd.DataFrame, holdings: dict, stale: bool = False) -> tuple[dict, str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    svc = RiskService(prices, holdings)
    risk = {}
    for m in METHODS:
        try:
            risk[m] = svc.var(m, 0.99)
        except Exception as e:  # noqa: BLE001
            risk[m] = {"error": str(e)}
    contrib = svc.contributions("historical", "es", 0.99)
    stress = {s["name"]: svc.stress(s["name"]) for s in svc.scenarios()["scenarios"]}
    end = pd.Timestamp(svc.latest)
    bt = rolling_var(holdings, prices, "historical", 0.99, 500,
                     start=end - pd.DateOffset(days=550), end=end)
    tl = jsonable(traffic_light(bt["exception"].to_numpy()[-250:]))
    bt_sum = jsonable(summarize(bt.iloc[-250:], 0.99))
    change = svc.explain_change()

    fig, ax = plt.subplots(figsize=(10, 3.5))
    last = bt.iloc[-250:]
    ax.plot(last.index, last["loss"] / 1e3, color="#9aa0a6", lw=0.8, label="loss")
    ax.plot(last.index, last["var"] / 1e3, color="#1f77b4", label="99% hist VaR")
    e = last[last["exception"]]
    ax.scatter(e.index, e["loss"] / 1e3, color="red", zorder=3, label="exception")
    ax.set_ylabel("HKD k")
    ax.legend(fontsize=8)
    chart_bt = _png(fig)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 3.5))
    comps = contrib["components"]
    ax.barh([c["ticker"] for c in comps][::-1], [c["component"] / 1e3 for c in comps][::-1])
    ax.set_xlabel("component ES, HKD k")
    chart_ces = _png(fig)
    plt.close(fig)

    report = {
        "as_of": svc.latest, "generated_at": datetime.now(UTC).isoformat(),
        "stale": stale, "currency": "HKD", "portfolio": svc.portfolio(), "risk_99": risk,
        "top5_es_contributors": comps[:5], "stress": stress, "traffic_light_250d": tl,
        "backtest_250d": bt_sum, "var_change_5d": change,
    }
    html = Template(HTML).render(r=report, chart_bt=chart_bt, chart_ces=chart_ces)
    return jsonable(report), html


HTML = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>HK Risk Report {{ r.as_of }}</title><style>
body{font-family:-apple-system,Segoe UI,sans-serif;max-width:960px;margin:24px auto;padding:0 16px;
color:#1d1d1f;background:#fff}table{border-collapse:collapse;width:100%;margin:8px 0 20px}
td,th{border-bottom:1px solid #e5e5e5;padding:6px 8px;text-align:right}td:first-child,th:first-child
{text-align:left}.stale{background:#fff3cd;padding:8px;border-radius:6px}.green{color:#1a7f37}
.yellow{color:#9a6700}.red{color:#cf222e}img{max-width:100%}</style></head><body>
<h1>HK Portfolio Risk Report</h1>
<p>As of <b>{{ r.as_of }}</b> &middot; value HKD {{ "{:,.0f}".format(r.portfolio.total_value) }}
&middot; generated {{ r.generated_at[:16] }} UTC</p>
{% if r.stale %}<p class="stale">STALE: price refresh failed, figures use the previous cache.</p>{% endif %}
<h2>1-day VaR / ES at 99% (HKD)</h2><table><tr><th>Method</th><th>VaR</th><th>% value</th><th>ES</th></tr>
{% for m, x in r.risk_99.items() %}<tr><td>{{ m }}</td>{% if x.error %}<td colspan=3>{{ x.error }}</td>
{% else %}<td>{{ "{:,.0f}".format(x.var) }}</td><td>{{ "{:.2%}".format(x.var_pct) }}</td>
<td>{{ "{:,.0f}".format(x.es) if x.es is not none else "n/a" }}</td>{% endif %}</tr>{% endfor %}</table>
<p>VaR change over 5 trading days: HKD {{ "{:+,.0f}".format(r.var_change_5d.var_change) }}
(price/position {{ "{:+,.0f}".format(r.var_change_5d.price_position_effect) }},
window roll {{ "{:+,.0f}".format(r.var_change_5d.window_roll_effect) }}).</p>
<h2>Top 5 contributors to 99% historical ES</h2><table><tr><th>Ticker</th><th>Value</th>
<th>Component ES</th><th>Share</th></tr>{% for c in r.top5_es_contributors %}<tr><td>{{ c.ticker }}</td>
<td>{{ "{:,.0f}".format(c.position_value) }}</td><td>{{ "{:,.0f}".format(c.component) }}</td>
<td>{{ "{:.1%}".format(c.pct_of_total) }}</td></tr>{% endfor %}</table>
<img src="data:image/png;base64,{{ chart_ces }}" alt="component ES">
<h2>Stress scenarios</h2><table><tr><th>Scenario</th><th>Window</th><th>P&amp;L HKD</th><th>%</th>
<th>Proxied</th></tr>{% for k, s in r.stress.items() %}<tr><td>{{ k }}</td><td>{{ s.start }} &rarr; {{ s.end }}</td>
<td>{{ "{:,.0f}".format(s.total_pnl) }}</td><td>{{ "{:.1%}".format(s.total_pnl_pct) }}</td>
<td>{{ s.proxied|join(", ") or "-" }}</td></tr>{% endfor %}</table>
<h2>Backtest, last 250 days (historical 99%)</h2>
<p>Basel zone: <b class="{{ r.traffic_light_250d.zone }}">{{ r.traffic_light_250d.zone|upper }}</b>
({{ r.traffic_light_250d.count }} exceptions; Kupiec p = {{ "{:.3f}".format(r.backtest_250d.kupiec_p) }})</p>
<img src="data:image/png;base64,{{ chart_bt }}" alt="backtest">
</body></html>"""


def run_local(out_dir: Path, refresh: bool = True) -> Path:
    holdings = load_portfolio()
    cache_path = Path(os.getenv("HKRISK_LIVE_CACHE", "data/prices_live.parquet"))
    cache = pd.read_parquet(cache_path) if cache_path.exists() else load_snapshot()
    prices, stale = refresh_prices(cache, list(cache.columns)) if refresh else (cache, False)
    if not stale:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        prices.to_parquet(cache_path)
    report, html = build_report(prices, holdings, stale)
    d = out_dir / report["as_of"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "report.json").write_text(json.dumps(report, indent=2))
    (d / "report.html").write_text(html)
    return d


def handler(event=None, context=None):
    """AWS Lambda entry point (EventBridge Scheduler, weekdays 18:30 Asia/Hong_Kong)."""
    import boto3

    bucket = os.environ["REPORT_BUCKET"]
    s3 = boto3.client("s3")
    holdings = load_portfolio()
    local = Path("/tmp/prices_live.parquet")
    try:
        s3.download_file(bucket, "data/prices_live.parquet", str(local))
        cache = pd.read_parquet(local)
    except Exception:  # noqa: BLE001  first run: seed from the committed snapshot
        cache = load_snapshot()
    prices, stale = refresh_prices(cache, list(cache.columns))
    latest = prices.dropna(subset=list(holdings)).index[-1].strftime("%Y-%m-%d")
    key = f"reports/{latest}/report.json"
    if not stale:
        try:
            s3.head_object(Bucket=bucket, Key=key)
            return {"status": "skipped", "reason": f"no new trading day since {latest}"}
        except s3.exceptions.ClientError:
            pass
        prices.to_parquet(local)
        s3.upload_file(str(local), bucket, "data/prices_live.parquet")
    report, html = build_report(prices, holdings, stale)
    s3.put_object(Bucket=bucket, Key=key, Body=json.dumps(report).encode(),
                  ContentType="application/json")
    s3.put_object(Bucket=bucket, Key=f"reports/{latest}/report.html", Body=html.encode(),
                  ContentType="text/html")
    s3.put_object(Bucket=bucket, Key="reports/latest.html", Body=html.encode(),
                  ContentType="text/html")
    return {"status": "ok", "as_of": latest, "stale": stale}
