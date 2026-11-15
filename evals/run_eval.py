"""Run the 50-question eval and grade it.

    uv run python evals/run_eval.py                    # all questions, provider from .env
    uv run python evals/run_eval.py --split holdout    # report on held-out set only
    uv run python evals/run_eval.py --ids d01 s01 --sleep 3 --provider gemini

Writes evals/results/<timestamp>.json and prints a score table by category.
Failure classes: wrong_tool, number_misquoted, hallucinated_number, missing_text,
no_refusal, error. (Grader bugs are found by reading answers: see --show.)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import traceback
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import yaml

from hkrisk.agent.grounding import contains_value, grounding
from hkrisk.agent.loop import ask
from hkrisk.agent.ratelimit import QuotaExhausted
from hkrisk.service import RiskService

HERE = Path(__file__).parent
NAMES = {"0700.HK": "tencent", "3690.HK": "meituan", "0005.HK": "hsbc", "0939.HK": "ccb|construction",
         "1299.HK": "aia", "0388.HK": "hkex|exchanges", "0016.HK": "sun hung kai|shkp",
         "0941.HK": "china mobile", "2800.HK": "tracker"}
REFUSAL = re.compile(r"can(?:no|')t|unable|not able|don't have|do not have|no tool|outside|"
                     r"not (?:possible|available|supported)|not something|isn't something|"
                     r"not in (?:your|the) portfolio|not provide|cannot provide", re.IGNORECASE)


def _eval(expr: str, svc: RiskService):
    # questions.yaml is a trusted local file, but evaluate with no builtins anyway
    env = {"__builtins__": {}, "svc": svc, "next": next, "min": min, "max": max, "abs": abs}
    return eval(expr, env)


METHOD_ALIASES = {"t": "student|t-distribution|t distribution|t model", "evt": "evt|extreme value",
                  "garch": "garch", "normal": "normal|variance-covariance|gaussian"}


def _text_ok(answer: str, want: str) -> bool:
    """Whole-word, case-insensitive; 'a|b' = either; tickers also match names / bare codes.
    A bare "t" is never matched literally (it occurs in "don't"); Student-t aliases are used."""
    alts = []
    for w in want.lower().split("|"):
        if w in METHOD_ALIASES:
            alts += METHOD_ALIASES[w].split("|")
            continue
        alts.append(w)
        if w.upper() in NAMES:
            alts += NAMES[w.upper()].split("|") + [w.split(".")[0]]
    return any(re.search(r"\b" + re.escape(x) + r"\b", answer, re.IGNORECASE) for x in alts)


def grade(q: dict, r, svc: RiskService) -> dict:
    calls = [c.__dict__ for c in r.tool_calls]
    called = {c["name"] for c in calls}
    g = grounding(r.answer, calls)
    out = {"tools_called": sorted(called), "grounding": g, "failures": []}
    if q.get("should_refuse"):
        # any numbers it volunteers (e.g. offering the VaR instead) must be grounded
        refused = bool(REFUSAL.search(r.answer)) and g["grounded"]
        out["tool_ok"] = True
        out["numeric_ok"] = refused
        if not refused:
            out["failures"].append("no_refusal")
        out["passed"] = refused
        return out
    if q.get("grounded_only"):
        # no single right number (ambiguous / adversarial): pass iff the answer is non-empty,
        # every number in it is traceable to a tool result, and no injected text is repeated
        bad = [t for t in q.get("expected_not_text", []) if _text_ok(r.answer, t)]
        ok = bool(r.answer.strip()) and g["grounded"] and not bad
        out.update(tool_ok=True, numeric_ok=ok, passed=ok)
        if not g["grounded"]:
            out["failures"].append(f"hallucinated_number {g['ungrounded']}")
        if bad:
            out["failures"].append(f"contradicting_text {bad}")
        return out
    missing = [t for t in q.get("expected_tools", []) if t not in called]
    out["tool_ok"] = not missing
    if missing:
        out["failures"].append(f"wrong_tool (missing {missing})")
    exp_vals = [_eval(e, svc) for e in q.get("expected", [])]
    out["expected_values"] = exp_vals
    num_ok = all(contains_value(r.answer, v, q["tolerance"]) for v in exp_vals)
    if not num_ok:
        out["failures"].append("number_misquoted")
    texts = [str(_eval(t, svc)) if t.startswith(("svc.", "max(", "min(")) else t
             for t in q.get("expected_text", [])]
    out["expected_text"] = texts
    txt_ok = all(_text_ok(r.answer, t) for t in texts)
    if not txt_ok:
        out["failures"].append(f"missing_text {texts}")
    bad = [t for t in q.get("expected_not_text", []) if _text_ok(r.answer, t)]
    if bad:
        txt_ok = False
        out["failures"].append(f"contradicting_text {bad}")
    if not g["grounded"]:
        out["failures"].append(f"hallucinated_number {g['ungrounded']}")
    out["numeric_ok"] = num_ok and txt_ok
    out["passed"] = out["numeric_ok"] and out["tool_ok"] and g["grounded"]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "holdout", "all"], default="all")
    ap.add_argument("--ids", nargs="*")
    ap.add_argument("--provider")
    ap.add_argument("--model")
    ap.add_argument("--sleep", type=float, default=float(os.getenv("EVAL_SLEEP", "0")),
                    help="extra seconds between questions (pacing is done by LLM_RPM/TPM/RPD)")
    ap.add_argument("--show", action="store_true", help="print every answer")
    ap.add_argument("--note", default="", help="what changed in this run")
    ap.add_argument("--regrade", metavar="RESULTS_JSON",
                    help="re-score saved answers with the current grader (no LLM calls); "
                         "use after fixing a grader bug")
    args = ap.parse_args(argv)
    if args.regrade:
        return regrade(Path(args.regrade))

    cfg = yaml.safe_load((HERE / "questions.yaml").read_text())
    qs = [{**cfg["defaults"], **q} for q in cfg["questions"]]
    if args.ids:
        qs = [q for q in qs if q["id"] in args.ids]
    elif args.split != "all":
        qs = [q for q in qs if q["split"] == args.split]
    svc = RiskService.from_env()

    rows = []
    stopped = None
    for i, q in enumerate(qs):
        try:
            r = ask(q["question"], service=svc, provider=args.provider, model=args.model)
            gr = grade(q, r, svc)
            row = {**q, **gr, "answer": r.answer, "tool_calls": [c.__dict__ for c in r.tool_calls],
                   "input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
                   "latency_s": r.latency_s, "iterations": r.iterations,
                   "stop_reason": r.stop_reason, "provider": r.provider, "model": r.model}
        except QuotaExhausted as e:  # stop cleanly; don't score unanswered questions as fails
            stopped = (str(e), [x["id"] for x in qs[i:]])
            print(f"STOPPED: {e}", flush=True)
            break
        except Exception as e:  # noqa: BLE001
            row = {**q, "passed": False, "tool_ok": False, "numeric_ok": False,
                   "failures": [f"error {type(e).__name__}: {e} {getattr(e, 'body', '') or ''}"], "answer": "",
                   "trace": traceback.format_exc(), "grounding": {"grounded": False}}
        rows.append(row)
        flag = "PASS" if row["passed"] else "FAIL"
        print(f"[{i + 1:2d}/{len(qs)}] {flag} {q['id']} {row.get('failures', '')}", flush=True)
        if args.show or not row["passed"]:
            print("      Q:", q["question"], "\n      A:", (row["answer"] or "")[:600]
                  .replace("\n", " "), flush=True)
        time.sleep(args.sleep)

    if not rows:
        print("no questions answered;", stopped[0] if stopped else "")
        return 1
    summary = summarize(rows)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (HERE / "results").mkdir(exist_ok=True)
    path = HERE / "results" / f"{stamp}.json"
    path.write_text(json.dumps({"note": args.note, "summary": summary, "rows": rows,
                                "unanswered_ids": stopped[1] if stopped else []},
                               indent=2, default=str))
    print_table(summary)
    print("saved", path)
    if stopped:
        print(f"\nPARTIAL RUN ({len(rows)}/{len(qs)}). Resume after the quota resets with:\n"
              f"  uv run python evals/run_eval.py --ids {' '.join(stopped[1])}")


def regrade(path: Path) -> int:
    from types import SimpleNamespace

    from hkrisk.agent.loop import ToolCall

    saved = json.loads(path.read_text())
    cfg = yaml.safe_load((HERE / "questions.yaml").read_text())
    qmap = {q["id"]: {**cfg["defaults"], **q} for q in cfg["questions"]}
    svc = RiskService.from_env()
    rows = []
    for old in saved["rows"]:
        if "trace" in old:  # errored run: nothing to re-grade
            rows.append(old)
            continue
        q = qmap[old["id"]]
        r = SimpleNamespace(answer=old["answer"],
                            tool_calls=[ToolCall(**c) for c in old["tool_calls"]])
        new = {**old, **q, **grade(q, r, svc)}
        if new["passed"] != old["passed"]:
            print(f"{old['id']}: {'PASS' if old['passed'] else 'FAIL'} -> "
                  f"{'PASS' if new['passed'] else 'FAIL'} {new['failures']}")
        rows.append(new)
    summary = summarize(rows)
    out = path.with_name(path.stem + "-regraded.json")
    out.write_text(json.dumps({"note": saved.get("note", "") + " [regraded]",
                               "regraded_from": path.name, "summary": summary, "rows": rows},
                              indent=2, default=str))
    print_table(summary)
    print("saved", out)
    return 0


def summarize(rows):
    by = defaultdict(list)
    for r in rows:
        by[r["category"]].append(r)
        by[f"split:{r['split']}"].append(r)
        by["ALL"].append(r)

    def stats(rs):
        n = len(rs)
        nums = [r for r in rs if r.get("grounding", {}).get("numbers", 0) > 0]
        return {"n": n, "passed": sum(r["passed"] for r in rs),
                "accuracy": sum(r["passed"] for r in rs) / n if n else 0,
                "tool_correct": sum(bool(r.get("tool_ok")) for r in rs) / n if n else 0,
                "grounding_rate": (sum(r["grounding"]["grounded"] for r in nums) / len(nums)
                                   if nums else 1.0),
                "input_tokens": sum(r.get("input_tokens", 0) for r in rs),
                "output_tokens": sum(r.get("output_tokens", 0) for r in rs),
                "mean_latency_s": (sum(r.get("latency_s", 0) for r in rs) / n) if n else 0}
    return {k: stats(v) for k, v in sorted(by.items())}


def print_table(s):
    print(f"\n{'group':18s} {'n':>3s} {'acc':>6s} {'tools':>6s} {'ground':>7s} {'lat s':>6s}")
    for k, v in s.items():
        print(f"{k:18s} {v['n']:3d} {v['accuracy']:6.0%} {v['tool_correct']:6.0%} "
              f"{v['grounding_rate']:7.0%} {v['mean_latency_s']:6.1f}")


if __name__ == "__main__":
    sys.exit(main())
