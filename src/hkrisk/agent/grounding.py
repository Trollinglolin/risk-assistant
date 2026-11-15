"""Find the numbers in an answer and check each one against tool results."""

from __future__ import annotations

import re

_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2} [A-Z][a-z]{2,8} \d{4}\b|"
                   r"\b[A-Z][a-z]{2,8} \d{1,2},? \d{4}\b|\b(19|20)\d{2}\b")
_TICKER = re.compile(r"\b\d{4}\.HK\b|\^HSI|\b(?:0700|3690|0005|0939|1299|0388|0016|0941|2800)\b"
                     r"|\b[A-Za-z]+\(\d+,\s*\d+\)")  # tickers, GARCH(1,1)
# window / horizon descriptors such as "250-day", "500 trading days", "5 years"
_DESCRIPTOR = re.compile(r"\b\d+(?:\.\d+)?(?:-| )(?:trading[- ])?(?:day|year)s?\b", re.IGNORECASE)
# a confidence level is a setting, not a result: "99% confidence", "97.5% VaR", "95% ES"
_CONFIDENCE = re.compile(r"\b(?:9\d|9\d\.\d+)\s?%(?=\s*(?:confidence|var\b|es\b|expected "
                         r"shortfall|value[- ]at[- ]risk|1-day|one-day|10-day))", re.IGNORECASE)
_NUM = re.compile(r"(?<![\w.])([-−]?\d[\d,]*(?:\.\d+)?)\s*(%|[kKmM]\b|million\b|bn\b|billion\b)?")
_SCALE = {"k": 1e3, "m": 1e6, "million": 1e6, "bn": 1e9, "billion": 1e9}


def extract_numbers(text: str) -> list[dict]:
    """Numbers as written: value, decimals shown, unit suffix."""
    t = _CONFIDENCE.sub(" ", _DESCRIPTOR.sub(" ", _TICKER.sub(" ", _DATE.sub(" ", text))))
    out = []
    for m in _NUM.finditer(t):
        raw = m.group(1).replace(",", "").replace("−", "-")
        try:
            v = float(raw)
        except ValueError:
            continue
        dec = len(raw.split(".")[1]) if "." in raw else 0
        unit = (m.group(2) or "").lower()
        out.append({"text": m.group(0).strip(), "value": v, "decimals": dec, "unit": unit})
    return out


def _flatten(x, acc: list[float]):
    if isinstance(x, dict):
        for v in x.values():
            _flatten(v, acc)
    elif isinstance(x, (list, tuple)):
        for v in x:
            _flatten(v, acc)
    elif isinstance(x, bool) or x is None:
        return
    elif isinstance(x, (int, float)):
        acc.append(float(x))
    elif isinstance(x, str):
        for n in extract_numbers(x):
            acc.append(n["value"])
    return acc


def tool_numbers(tool_calls) -> list[float]:
    acc: list[float] = []
    for c in tool_calls:
        c = c if isinstance(c, dict) else c.__dict__
        _flatten(c.get("output"), acc)
        _flatten(c.get("input"), acc)
    return acc


def _half_ulp(n: dict) -> float:
    """Half a unit in the last shown digit; trailing zeros of integers count as rounding
    (108,000 -> +/-500)."""
    if n["decimals"] > 0:
        return 0.5 * 10 ** (-n["decimals"])
    digits = str(int(abs(n["value"])))
    tz = len(digits) - len(digits.rstrip("0")) if digits != "0" else 0
    return 0.5 * 10 ** tz


def number_matches(n: dict, v: float, rel: float = 1e-4) -> bool:
    """Is the written number n a correctly rounded quote of value v?

    Allowed display scalings: k/m/bn suffixes; % for fractions (0.0229 -> 2.29%); a bare
    fraction written as a percentage number. Sign may be flipped (loss quoted as positive).
    """
    shown = n["value"]
    if n["unit"] in _SCALE:
        cands = [v / _SCALE[n["unit"]]]
    elif n["unit"] == "%":
        cands = [v * 100, v]
    else:
        cands = [v] + ([v * 100] if abs(v) <= 1 else [])
    tol_shown = _half_ulp(n) * 1.0001
    for c in cands:
        for s in (shown, -shown):
            if abs(s - c) <= max(tol_shown, rel * abs(c)):
                return True
    return False


def grounding(answer: str, tool_calls, trivial_max: float = 10) -> dict:
    """Every non-trivial number in the answer must match some tool input/output value."""
    vals = tool_numbers(tool_calls)
    ungrounded = []
    nums = extract_numbers(answer)
    for n in nums:
        if n["unit"] == "" and n["decimals"] == 0 and abs(n["value"]) <= trivial_max:
            continue  # small counts like "top 3", "1-day", "5 days"
        if not any(number_matches(n, v) for v in vals):
            ungrounded.append(n["text"])
    checked = [n for n in nums if not (n["unit"] == "" and n["decimals"] == 0
                                       and abs(n["value"]) <= trivial_max)]
    return {"numbers": len(checked), "ungrounded": ungrounded, "grounded": not ungrounded}


def contains_value(answer: str, expected: float, rel: float = 1e-4) -> bool:
    return any(number_matches(n, expected, rel) for n in extract_numbers(answer))
