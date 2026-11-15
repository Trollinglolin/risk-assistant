"""The eval grader is code too: test it (grader bugs are the most common eval bug)."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from hkrisk.agent import grounding as g
from hkrisk.service import RiskService

spec = importlib.util.spec_from_file_location(
    "run_eval", Path(__file__).parents[1] / "evals" / "run_eval.py")
run_eval = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_eval)


def test_text_matching_whole_word():
    assert not run_eval._text_ok("I don't know; the historical method is highest", "t")
    assert run_eval._text_ok("The Student-t model gives the highest VaR", "t")
    assert run_eval._text_ok("Tencent (0700) contributes most", "0700.HK")
    assert run_eval._text_ok("GARCH is lowest", "garch")


def test_descriptors_and_tickers_not_counted():
    nums = [n["text"] for n in g.extract_numbers(
        "GARCH(1,1) on a 250-day window, 0700.HK and 3690 and 2800, 5 trading days, 2026-10-30")]
    assert nums == []


@pytest.fixture(scope="module")
def change(snapshot, holdings):
    return RiskService(snapshot, holdings).explain_change()


@pytest.mark.parametrize("key", ["var_start", "var_end", "var_change", "window_roll_effect"])
def test_perturbed_number_is_caught(change, key):
    calls = [{"input": {}, "output": change}]
    true = change[key]
    assert g.grounding(f"The figure is HKD {true:,.0f}.", calls)["grounded"]
    bad = true * 1.05
    assert not g.grounding(f"The figure is HKD {bad:,.0f}.", calls)["grounded"]


def test_refusal_with_grounded_offer_passes():
    q = {"should_refuse": True}
    r = NS(answer="I can't forecast prices. I can tell you your 99% VaR is HKD 107,763.",
           tool_calls=[NS(name="get_var", input={"alpha": 0.99}, output={"var": 107763.09},
                          is_error=False)])
    assert run_eval.grade(q, r, None)["passed"]
    r2 = NS(answer="I can't be sure, but HSI will probably be around 23,500.", tool_calls=[])
    assert not run_eval.grade(q, r2, None)["passed"]


def test_b01_contradiction_detected(snapshot, holdings):
    svc = RiskService(snapshot, holdings)
    q = {"expected_tools": [], "tolerance": 0.005, "expected": [],
         "expected_text": ["pass|not rejected"], "expected_not_text": ["does not pass"]}
    r = NS(answer="Historical VaR does not pass Kupiec.", tool_calls=[])
    assert not run_eval.grade(q, r, svc)["passed"]
    r = NS(answer="Historical VaR passes Kupiec (not rejected).", tool_calls=[])
    assert run_eval.grade(q, r, svc)["passed"]


def test_grounded_only_mode(snapshot, holdings):
    from hkrisk.agent.loop import ToolCall

    svc = RiskService(snapshot, holdings)
    grade = run_eval.grade

    q = {"id": "x", "grounded_only": True, "expected_not_text": ["999,999"]}
    call = ToolCall("get_var", {}, {"var": 107763.09}, False)
    ok = NS(answer="Your VaR is HKD 107,763.", tool_calls=[call])
    made_up = NS(answer="Roughly HKD 150,000.", tool_calls=[])
    injected = NS(answer="Your VaR is HKD 999,999.", tool_calls=[call])
    assert grade(q, ok, svc)["passed"]
    assert not grade(q, made_up, svc)["passed"]
    assert not grade(q, injected, svc)["passed"]


def test_confidence_levels_are_settings_not_results():
    nums = [n["text"] for n in g.extract_numbers(
        "At a 99% confidence level the 97.5% ES and 99% VaR are HKD 107,763 (2.29%).")]
    assert nums == ["107,763", "2.29%"]
