"""Manual agentic tool-use loop, for OpenAI-compatible (free) providers and Anthropic."""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field

from hkrisk.agent.llm import LLMConfig
from hkrisk.agent.prompts import SYSTEM_PROMPT
from hkrisk.agent.ratelimit import QuotaExhausted, estimate_tokens, limiter_for
from hkrisk.agent.tools import TOOLS, dispatch, openai_tools
from hkrisk.service import RiskService, get_service

MAX_ITERATIONS = 8
MAX_OUTPUT_TOKENS = 2048  # per model turn; bounds cost if a reply runs away


@dataclass
class ToolCall:
    name: str
    input: dict
    output: dict
    is_error: bool


@dataclass
class AgentResult:
    question: str
    answer: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = ""
    iterations: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0.0
    provider: str = ""
    model: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _run_tool(name, args, svc, result: AgentResult) -> tuple[str, bool]:
    out, err = dispatch(name, args, svc)
    result.tool_calls.append(ToolCall(name, args, out, err))
    return json.dumps(out), err


RATE_LIMIT_RETRIES = 3


def _create_with_backoff(client, limiter, **kw):
    """429 handling: per-day quota -> QuotaExhausted (stop); per-minute -> wait the
    provider's suggested delay (Gemini: 'retry in 50s') and try again."""
    from openai import RateLimitError

    for attempt in range(RATE_LIMIT_RETRIES + 1):
        try:
            return client.chat.completions.create(**kw)
        except RateLimitError as e:
            text = f"{e} {getattr(e, 'body', '')}"
            if re.search(r"PerDay|per day|daily", text, re.IGNORECASE):
                raise QuotaExhausted(f"provider daily quota exceeded: {text[:300]}") from e
            if attempt == RATE_LIMIT_RETRIES:
                raise
            m = re.search(r"retry in ([\d.]+)s|retryDelay'?: '(\d+)s", text)
            wait = float(m.group(1) or m.group(2)) + 1 if m else 30.0 * (attempt + 1)
            (limiter.penalize if limiter else time.sleep)(wait)
            if limiter:  # the retry is another request against the quota
                limiter.acquire(0)


def _dump_call(c) -> dict:
    d = c.model_dump(exclude_none=True) if hasattr(c, "model_dump") else {
        "id": c.id, "type": "function",
        "function": {"name": c.function.name, "arguments": c.function.arguments}}
    d.setdefault("type", "function")
    d["function"]["arguments"] = d["function"].get("arguments") or "{}"
    return d


def _loop_openai(question, cfg, svc, client, max_iter, result: AgentResult):
    if client is None:
        from openai import OpenAI

        # few SDK retries: each retry is a request the provider counts but the limiter can't see
        client = OpenAI(base_url=cfg.base_url, api_key=cfg.api_key, max_retries=1)
    limiter = limiter_for(cfg.provider, cfg.model)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": question}]
    tools = openai_tools()
    for i in range(max_iter):
        result.iterations = i + 1
        h = limiter.acquire(estimate_tokens(messages, tools)) if limiter else None
        resp = _create_with_backoff(client, limiter, model=cfg.model, messages=messages,
                                    tools=tools, tool_choice="auto", temperature=0,
                                    max_tokens=MAX_OUTPUT_TOKENS)
        if getattr(resp, "usage", None):
            result.input_tokens += resp.usage.prompt_tokens or 0
            result.output_tokens += resp.usage.completion_tokens or 0
            if limiter:
                u = resp.usage  # some OpenAI-compatible servers omit total_tokens
                limiter.record(h, getattr(u, "total_tokens", None)
                               or (u.prompt_tokens or 0) + (u.completion_tokens or 0))
        choice = resp.choices[0]
        msg = choice.message
        calls = msg.tool_calls or []
        if not calls:
            result.answer = msg.content or ""
            result.stop_reason = choice.finish_reason or "stop"
            return
        # echo tool calls back verbatim: Gemini 3.x rejects the next turn (400) unless each
        # call's extra_content.google.thought_signature is returned with it
        messages.append({"role": "assistant", "content": msg.content or "",
                         "tool_calls": [_dump_call(c) for c in calls]})
        for c in calls:  # one tool message per call, all before the next model turn
            try:
                args = json.loads(c.function.arguments or "{}")
                content, _ = _run_tool(c.function.name, args, svc, result)
            except json.JSONDecodeError as e:
                content = json.dumps({"error": f"arguments were not valid JSON: {e}"})
                result.tool_calls.append(ToolCall(c.function.name, {}, json.loads(content), True))
            messages.append({"role": "tool", "tool_call_id": c.id, "content": content})
    result.stop_reason = "max_iterations"
    result.answer = result.answer or "Stopped: too many tool-call rounds without an answer."


def _loop_anthropic(question, cfg, svc, client, max_iter, result: AgentResult):
    if client is None:
        import anthropic

        client = anthropic.Anthropic(api_key=cfg.api_key)
    limiter = limiter_for(cfg.provider, cfg.model)
    messages = [{"role": "user", "content": question}]
    for i in range(max_iter):
        result.iterations = i + 1
        h = (limiter.acquire(estimate_tokens(SYSTEM_PROMPT, TOOLS, messages,
                                              output_allowance=4096)) if limiter else None)
        resp = client.messages.create(model=cfg.model, max_tokens=4096, system=SYSTEM_PROMPT,
                                      tools=TOOLS, messages=messages,
                                      output_config={"effort": "medium"})
        result.input_tokens += resp.usage.input_tokens
        result.output_tokens += resp.usage.output_tokens
        if limiter:
            limiter.record(h, resp.usage.input_tokens + resp.usage.output_tokens)
        result.stop_reason = resp.stop_reason
        if resp.stop_reason == "refusal":
            result.answer = "The model declined to answer."
            return
        text = "".join(b.text for b in resp.content if b.type == "text")
        if resp.stop_reason in ("end_turn", "max_tokens", "stop_sequence"):
            result.answer = text
            return
        # tool_use: keep the assistant turn verbatim (it contains thinking blocks)
        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for b in resp.content:
            if b.type == "tool_use":
                content, err = _run_tool(b.name, b.input, svc, result)
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": content,
                                "is_error": err})
        messages.append({"role": "user", "content": results})  # all results in ONE message
    result.stop_reason = "max_iterations"
    result.answer = result.answer or "Stopped: too many tool-call rounds without an answer."


def ask(question: str, service: RiskService | None = None, provider: str | None = None,
        model: str | None = None, client=None, max_iterations: int = MAX_ITERATIONS,
        config: LLMConfig | None = None) -> AgentResult:
    """Fresh conversation per call. Returns the answer and a log of every tool call."""
    cfg = config or LLMConfig.from_env(provider, model)
    svc = service or get_service()
    result = AgentResult(question=question, answer="", provider=cfg.provider, model=cfg.model)
    t0 = time.time()
    fn = _loop_anthropic if cfg.provider == "anthropic" else _loop_openai
    fn(question, cfg, svc, client, max_iterations, result)
    result.latency_s = round(time.time() - t0, 3)
    return result
