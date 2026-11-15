"""Tool definitions (provider-neutral JSON Schema) and dispatch to the engine."""

from __future__ import annotations

import hashlib
import json
import logging

from jsonschema import Draft202012Validator

from hkrisk.service import RiskService

audit = logging.getLogger("hkrisk.audit")

METHOD_ENUM = ["historical", "normal", "t", "garch", "evt"]
_alpha = {"type": "number", "description": "Confidence level as a decimal, e.g. 0.99 for 99%, "
          "0.975 for 97.5%. Default 0.99.", "exclusiveMinimum": 0.5, "exclusiveMaximum": 1}
_window = {"type": "integer", "description": "Look-back window in trading days. Default 500 "
           "(about 2 years).", "minimum": 50, "maximum": 3000}
_as_of = {"type": "string", "description": "Valuation date YYYY-MM-DD. Omit for the latest "
          "available date. Only data up to this date is used."}

TOOLS = [
    {
        "name": "get_portfolio",
        "description": "Current holdings: shares, HKD price, HKD market value and weight per "
                       "position, plus total portfolio value in HKD. Use for questions about "
                       "what is held, position sizes, weights or total value.",
        "input_schema": {"type": "object", "properties": {"as_of": _as_of}},
    },
    {
        "name": "get_var",
        "description": "1-day Value-at-Risk AND Expected Shortfall of the whole portfolio for ONE "
                       "method. Returns var and es in HKD (positive = loss), var_pct/es_pct as "
                       "decimal fractions of portfolio value, plus as_of, method, alpha, window. "
                       "Methods: historical (default), normal, t (Student-t), garch (GARCH(1,1) "
                       "filtered historical simulation), evt (peaks-over-threshold GPD). Use for "
                       "any 'what is my VaR / ES / expected shortfall' question. horizon_days>1 "
                       "applies sqrt-time scaling.",
        "input_schema": {"type": "object", "properties": {
            "method": {"type": "string", "enum": METHOD_ENUM}, "alpha": _alpha,
            "window": _window, "as_of": _as_of,
            "horizon_days": {"type": "integer", "minimum": 1, "maximum": 10,
                             "description": "Holding period in days (default 1)."}}},
    },
    {
        "name": "compare_var_methods",
        "description": "Runs ALL five methods and returns them ranked by VaR (highest first), "
                       "with es, plus highest_var_method and lowest_var_method. Use for "
                       "'which method gives the highest/lowest', or 'compare methods' questions.",
        "input_schema": {"type": "object", "properties": {"alpha": _alpha, "window": _window,
                                                          "as_of": _as_of}},
    },
    {
        "name": "get_risk_contributions",
        "description": "Euler risk attribution: each position's component of total VaR or ES "
                       "in HKD and as pct_of_total (decimal), sorted largest first; components "
                       "sum to the total. measure='var' supports method historical or normal; "
                       "measure='es' supports historical only. Use for 'which holding drives / "
                       "contributes most to risk' questions. A negative component is a hedge.",
        "input_schema": {"type": "object", "properties": {
            "method": {"type": "string", "enum": ["historical", "normal"]},
            "measure": {"type": "string", "enum": ["var", "es"]},
            "alpha": _alpha, "window": _window, "as_of": _as_of}},
    },
    {
        "name": "explain_var_change",
        "description": "Explains why VaR changed between two dates (default: the last 5 trading "
                       "days, i.e. 'this week'). Returns var_start, var_end, var_change, the "
                       "split into price_position_effect and window_roll_effect, per-position "
                       "component deltas, top contributors at the end date, and the days that "
                       "entered/left the window with their losses. Use for 'what drove / "
                       "changed / moved my VaR' questions; in the answer, name the 1-2 "
                       "holdings with the largest absolute delta in position_deltas.",
        "input_schema": {"type": "object", "properties": {
            "start_date": {"type": "string", "description": "YYYY-MM-DD; default 5 trading "
                           "days before end_date"},
            "end_date": {"type": "string", "description": "YYYY-MM-DD; default latest"},
            "method": {"type": "string", "enum": ["historical", "normal"]},
            "alpha": _alpha, "window": _window}},
    },
    {
        "name": "list_scenarios",
        "description": "Lists available historical stress scenarios (name, start, end, HSI "
                       "drawdown). Call this first if unsure of a scenario name.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "run_stress_test",
        "description": "Applies a historical crisis (each stock's peak-to-trough return) to "
                       "today's positions. Returns total_pnl in HKD (negative = loss), "
                       "total_pnl_pct, per-position pnl, and 'proxied' = tickers that did not "
                       "exist then and were mapped via beta to the HSI move. Scenarios: "
                       "gfc_2008, covid_2020, china_tech_2022.",
        "input_schema": {"type": "object", "required": ["scenario"], "properties": {
            "scenario": {"type": "string", "enum": ["gfc_2008", "covid_2020", "china_tech_2022"]},
            "as_of": _as_of}},
    },
    {
        "name": "run_hsi_shock",
        "description": "Hypothetical stress: Hang Seng Index moves by `shock` (decimal, e.g. "
                       "-0.2 for -20%) and each position moves by beta x shock. Returns total "
                       "and per-position HKD P&L and betas.",
        "input_schema": {"type": "object", "required": ["shock"], "properties": {
            "shock": {"type": "number", "minimum": -0.9, "maximum": 0.9}, "as_of": _as_of}},
    },
    {
        "name": "run_backtest",
        "description": "Rolling out-of-sample VaR backtest (default: full available history, about 6 years; or the last `years` years): "
                       "exception count vs expected, Kupiec POF p-value and kupiec_pass, "
                       "Christoffersen independence and conditional-coverage p-values, latest "
                       "250-day Basel traffic-light zone, and counts of rolling 250-day windows "
                       "in each zone. Use for 'does the model pass / backtest / traffic light'.",
        "input_schema": {"type": "object", "properties": {
            "method": {"type": "string", "enum": METHOD_ENUM}, "alpha": _alpha,
            "years": {"type": "number", "minimum": 1, "maximum": 6,
                      "description": "Test period length in years. Omit for the full available history (about 6 years, from 2020-10-05)."}}},
    },
]

TOOL_NAMES = {t["name"] for t in TOOLS}


_PCT_KEYS = ("weight", "pct", "shock", "drawdown")


def _with_display_pcts(x):
    """Add a pre-formatted '<key>_display' (e.g. es_pct 0.048570 -> "4.86%") next to every
    fraction-of-something field, so the model quotes percentages without converting them
    itself (an early eval run caught it truncating 4.857% to "4.85%")."""
    if isinstance(x, list):
        return [_with_display_pcts(v) for v in x]
    if not isinstance(x, dict):
        return x
    out = {}
    for k, v in x.items():
        out[k] = _with_display_pcts(v)
        if (isinstance(v, float) and not isinstance(v, bool) and abs(v) <= 5
                and any(k == p or k.endswith("_" + p) or k.startswith(p) for p in _PCT_KEYS)):
            out[k + "_display"] = f"{v * 100:.2f}%"
    return out


MAX_ROWS = 15
_RANK_KEY = {"positions": ("value", "pnl"), "components": ("component",),
             "position_deltas": ("delta",)}


def _trim_lists(out: dict) -> dict:
    """Keep the MAX_ROWS largest rows (by |value|) of long per-holding lists.

    The 95-name HSI book would otherwise put ~5k tokens of rows into every tool result. The
    totals are computed by the engine on the full book, so nothing the model quotes changes;
    `<list>_omitted` tells it rows were left out.
    """
    out = dict(out)
    for key, ranks in _RANK_KEY.items():
        rows = out.get(key)
        if not isinstance(rows, list) or len(rows) <= MAX_ROWS:
            continue
        rk = next((r for r in ranks if r in rows[0]), None)
        if rk is None:
            continue
        keep = sorted(rows, key=lambda r: abs(r.get(rk) or 0), reverse=True)[:MAX_ROWS]
        out[key] = keep
        out[f"{key}_omitted"] = len(rows) - MAX_ROWS
        out[f"{key}_note"] = (f"showing the {MAX_ROWS} largest by |{rk}| of {len(rows)}; "
                              "totals cover all holdings")
    return out


# Deny-by-default argument validation: every tool's JSON Schema is closed
# (additionalProperties: false), and arguments are checked before any engine code runs.
# All 9 tools are read-only (no writes, no network, no shell), so no human approval step is
# needed; the controls here bound what a prompt-injected model can make the engine compute.
_VALIDATORS = {t["name"]: Draft202012Validator({**t["input_schema"], "additionalProperties": False})
               for t in TOOLS}


def _validate(name: str, args: dict) -> str | None:
    v = _VALIDATORS.get(name)
    if v is None:
        return f"unknown tool {name!r}; available: {sorted(TOOL_NAMES)}"
    errs = sorted(v.iter_errors(args), key=lambda e: list(e.path))
    if errs:
        e = errs[0]
        where = ".".join(str(x) for x in e.path) or "arguments"
        return f"invalid {where}: {e.message}"
    return None


def dispatch(name: str, args: dict | None, svc: RiskService) -> tuple[dict, bool]:
    """Run a tool. Returns (result, is_error). Never raises on bad input."""
    # some providers send explicit nulls for omitted optional arguments
    a = {k: v for k, v in (args or {}).items() if v is not None} if isinstance(args, dict) else args
    problem = "arguments must be a JSON object" if not isinstance(a, dict) else _validate(name, a)
    if problem:
        out, err = {"error": problem}, True
    else:
        out, err = _dispatch(name, a, svc)
    audit.info("tool_call portfolio=%s tool=%s args_sha256=%s error=%s",
               getattr(svc, "name", "?"), name,
               hashlib.sha256(json.dumps(args, sort_keys=True, default=str).encode())
               .hexdigest()[:12], err)
    return (out if err else _with_display_pcts(_trim_lists(out))), err


def _dispatch(name: str, args: dict | None, svc: RiskService) -> tuple[dict, bool]:
    a = dict(args or {})
    try:
        if name == "get_portfolio":
            return svc.portfolio(a.get("as_of")), False
        if name == "get_var":
            return svc.var(a.get("method", "historical"), a.get("alpha", 0.99),
                           a.get("window", 500), a.get("as_of"), a.get("horizon_days", 1)), False
        if name == "compare_var_methods":
            return svc.compare_methods(a.get("alpha", 0.99), a.get("window", 500),
                                       a.get("as_of")), False
        if name == "get_risk_contributions":
            return svc.contributions(a.get("method", "historical"), a.get("measure", "var"),
                                     a.get("alpha", 0.99), a.get("window", 500),
                                     a.get("as_of")), False
        if name == "explain_var_change":
            return svc.explain_change(a.get("start_date"), a.get("end_date"),
                                      a.get("method", "historical"), a.get("alpha", 0.99),
                                      a.get("window", 500)), False
        if name == "list_scenarios":
            return svc.scenarios(), False
        if name == "run_stress_test":
            return svc.stress(a["scenario"], a.get("as_of")), False
        if name == "run_hsi_shock":
            return svc.hsi_shock(float(a["shock"]), a.get("as_of")), False
        if name == "run_backtest":
            return svc.backtest(a.get("method", "historical"), a.get("years"),
                                a.get("alpha", 0.99)), False
        return {"error": f"unknown tool {name!r}; available: {sorted(TOOL_NAMES)}"}, True
    except KeyError as e:
        return {"error": f"missing required argument {e}"}, True
    except (ValueError, TypeError) as e:
        return {"error": str(e)}, True


def openai_tools() -> list[dict]:
    return [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                              "parameters": t["input_schema"]}} for t in TOOLS]
