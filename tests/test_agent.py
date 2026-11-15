import json
from types import SimpleNamespace as NS

import pytest

from hkrisk.agent import grounding as g
from hkrisk.agent.llm import LLMConfig
from hkrisk.agent.loop import ask
from hkrisk.agent.tools import TOOL_NAMES, TOOLS, dispatch
from hkrisk.service import RiskService


@pytest.fixture(scope="module")
def svc(snapshot, holdings):
    return RiskService(snapshot, holdings)


def test_tool_schemas_valid():
    for t in TOOLS:
        assert t["input_schema"]["type"] == "object" and len(t["description"]) > 40


@pytest.mark.parametrize("name,args", [
    ("get_portfolio", {}), ("get_var", {"method": "t", "alpha": 0.975}),
    ("compare_var_methods", {}), ("get_risk_contributions", {"measure": "es"}),
    ("explain_var_change", {}), ("list_scenarios", {}),
    ("run_stress_test", {"scenario": "covid_2020"}), ("run_hsi_shock", {"shock": -0.1}),
    ("run_backtest", {"method": "historical", "years": 3}),
])
def test_dispatch_ok(svc, name, args):
    out, err = dispatch(name, args, svc)
    assert not err, out
    json.dumps(out)  # serialisable, no NaN
    if name not in ("list_scenarios",):
        assert out["as_of"] and out["currency"] == "HKD"
    assert name in TOOL_NAMES


@pytest.mark.parametrize("name,args", [
    ("get_var", {"method": "bogus"}), ("get_var", {"alpha": 2}), ("run_stress_test", {}),
    ("run_stress_test", {"scenario": "y2k"}), ("nope", {}), ("run_hsi_shock", {"shock": -5}),
    ("get_var", {"as_of": "not-a-date"}),
])
def test_dispatch_errors_dont_raise(svc, name, args):
    out, err = dispatch(name, args, svc)
    assert err and "error" in out


def test_grounding():
    calls = [{"input": {"alpha": 0.99}, "output": {"var": 107763.09, "var_pct": 0.022854,
                                                   "as_of": "2026-10-30"}}]
    ok = "As of 2026-10-30 the 99% historical VaR is HKD 107,763 (2.29% of value), top 3."
    assert g.grounding(ok, calls)["grounded"]
    assert g.grounding("VaR is about HKD 0.11m", calls)["grounded"]
    bad = "VaR is HKD 150,000."
    assert g.grounding(bad, calls)["ungrounded"] == ["150,000"]
    assert g.contains_value(ok, 107763.09) and not g.contains_value(ok, 120000)


class FakeOpenAI:
    """Scripted OpenAI-compatible client: first asks for get_var, then answers."""

    def __init__(self):
        self.calls = 0
        self.chat = NS(completions=NS(create=self.create))

    def create(self, **kw):
        self.calls += 1
        usage = NS(prompt_tokens=10, completion_tokens=5)
        if self.calls == 1:
            tc = NS(id="c1", function=NS(name="get_var", arguments='{"alpha": 0.99}'))
            return NS(choices=[NS(message=NS(content=None, tool_calls=[tc]),
                                  finish_reason="tool_calls")], usage=usage)
        tool_msg = kw["messages"][-1]
        assert tool_msg["role"] == "tool" and tool_msg["tool_call_id"] == "c1"
        var = json.loads(tool_msg["content"])["var"]
        return NS(choices=[NS(message=NS(content=f"VaR is HKD {var:,.0f}", tool_calls=None),
                              finish_reason="stop")], usage=usage)


def test_loop_with_fake_client(svc):
    cfg = LLMConfig("groq", "fake", None, "x")
    r = ask("What's my 99% VaR?", service=svc, client=FakeOpenAI(), config=cfg)
    assert [c.name for c in r.tool_calls] == ["get_var"]
    assert g.contains_value(r.answer, r.tool_calls[0].output["var"])
    assert r.iterations == 2 and r.input_tokens == 20


def test_loop_max_iterations(svc):
    class Looper(FakeOpenAI):
        def create(self, **kw):
            tc = NS(id="c", function=NS(name="list_scenarios", arguments="{}"))
            return NS(choices=[NS(message=NS(content=None, tool_calls=[tc]),
                                  finish_reason="tool_calls")], usage=None)

    r = ask("loop", service=svc, client=Looper(), config=LLMConfig("groq", "f", None, "x"),
            max_iterations=3)
    assert r.stop_reason == "max_iterations" and len(r.tool_calls) == 3


@pytest.mark.live
def test_live_var_question(svc):
    r = ask("What's my 99% 1-day VaR?", service=svc)
    assert "get_var" in [c.name for c in r.tool_calls]
    expected = svc.var("historical", 0.99)["var"]
    assert g.contains_value(r.answer, expected), r.answer


def test_tool_calls_echoed_verbatim_with_thought_signature(svc):
    """Gemini 3.x returns 400 unless extra_content.google.thought_signature is sent back."""
    from openai.types.chat import ChatCompletionMessageToolCall

    sig = {"google": {"thought_signature": "abc123"}}
    tc = ChatCompletionMessageToolCall.model_validate(
        {"id": "c1", "type": "function", "extra_content": sig,
         "function": {"name": "list_scenarios", "arguments": "{}"}})
    seen = []

    def create(**kw):
        seen.append(kw["messages"])
        usage = NS(prompt_tokens=1, completion_tokens=1, total_tokens=2)
        if len(seen) == 1:
            return NS(choices=[NS(message=NS(content=None, tool_calls=[tc]),
                                  finish_reason="tool_calls")], usage=usage)
        return NS(choices=[NS(message=NS(content="done", tool_calls=None), finish_reason="stop")],
                  usage=usage)

    client = NS(chat=NS(completions=NS(create=create)))
    cfg = LLMConfig("gemini", "m", None, "k")
    ask("scenarios?", service=svc, client=client, config=cfg)
    echoed = seen[1][2]["tool_calls"][0]
    assert echoed["extra_content"] == sig and echoed["function"]["name"] == "list_scenarios"


def test_tool_outputs_carry_display_percentages(svc):
    out, err = dispatch("get_var", {"method": "historical"}, svc)
    assert not err
    assert out["es_pct_display"] == f"{out['es_pct'] * 100:.2f}%"
    out, _ = dispatch("get_risk_contributions", {}, svc)
    c = out["components"][0]
    assert c["pct_of_total_display"] == f"{c['pct_of_total'] * 100:.2f}%"
    assert "var_display" not in out and "total_display" not in out  # HKD amounts untouched


def test_long_lists_are_trimmed_for_the_model():
    from hkrisk.agent.tools import MAX_ROWS, _trim_lists

    rows = [{"ticker": f"T{i}", "component": float(i - 50)} for i in range(95)]
    out = _trim_lists({"total": 1.0, "components": rows})
    assert len(out["components"]) == MAX_ROWS and out["components_omitted"] == 95 - MAX_ROWS
    assert abs(out["components"][0]["component"]) == 50  # largest by absolute value first
    assert out["total"] == 1.0


@pytest.mark.parametrize("name,args,msg", [
    ("get_var", {"method": "historical", "rm": "-rf /"}, "Additional properties"),
    ("get_var", {"alpha": "0.99; DROP TABLE"}, "invalid alpha"),
    ("run_hsi_shock", {"shock": 5}, "invalid shock"),
    ("delete_everything", {}, "unknown tool"),
    ("get_var", ["not", "an", "object"], "JSON object"),
])
def test_tool_arguments_are_deny_by_default(svc, name, args, msg):
    out, err = dispatch(name, args, svc)
    assert err and msg in out["error"]


def test_null_optional_args_are_accepted(svc):
    out, err = dispatch("get_var", {"method": "historical", "as_of": None}, svc)
    assert not err and out["var"] > 0
