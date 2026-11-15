"""Client-side rate limiter for free-tier LLM APIs: requests/min, tokens/min, requests/day.

Configure with env vars (unset = no limit):
  LLM_RPM   requests per minute      e.g. 15
  LLM_TPM   tokens per minute        e.g. 250000   (input + output)
  LLM_RPD   requests per day         e.g. 500
  LLM_QUOTA_TZ  timezone the provider's daily quota resets in (Gemini: America/Los_Angeles)
  LLM_LIMIT_MARGIN  fraction of each limit to use (default 0.9: keep 10% headroom)

Before each model call, `acquire(estimate)` blocks until the call fits in the last-60-seconds
window for both requests and tokens. After the call, `record(actual)` swaps the estimate for the
token count the provider reports. The daily count is saved to disk so it survives across eval
runs; when it is used up, `QuotaExhausted` is raised instead of sending a request that would
fail.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

STATE_DIR = Path(os.getenv("HKRISK_QUOTA_DIR", Path.home() / ".cache" / "hkrisk"))


class QuotaExhausted(RuntimeError):
    """The daily request quota is used up (or a single call is bigger than the TPM limit)."""


def estimate_tokens(*payloads, output_allowance: int = 1000) -> int:
    """Conservative token estimate: ~3 chars/token for JSON-heavy text, plus room for output."""
    chars = sum(len(p if isinstance(p, str) else json.dumps(p, default=str)) for p in payloads)
    return chars // 3 + output_allowance


class RateLimiter:
    def __init__(self, rpm: int | None = None, tpm: int | None = None, rpd: int | None = None,
                 key: str = "default", tz: str = "UTC", margin: float = 0.9,
                 state_dir: Path | None = None, clock=time.time, sleep=time.sleep,
                 now=None):
        self.rpm = int(rpm * margin) if rpm else None
        self.tpm = int(tpm * margin) if tpm else None
        self.rpd = int(rpd * margin) if rpd else None
        self.tz = ZoneInfo(tz)
        self.key = key.replace("/", "_").replace(":", "_")
        self.state_dir = state_dir or STATE_DIR
        self._clock, self._sleep = clock, sleep
        self._now = now or (lambda: datetime.now(self.tz))
        self._lock = threading.Lock()
        # [unix time, tokens] of calls in the last minute; loaded from disk so back-to-back
        # runs (smoke test, then full eval) share one window
        self._events: deque[list] = deque(self._load().get("recent", []))

    # ---- daily counter (persisted) ----
    @property
    def _state_path(self) -> Path:
        return self.state_dir / f"quota_{self.key}.json"

    def _today(self) -> str:
        return self._now().strftime("%Y-%m-%d")

    def _load(self) -> dict:
        try:
            return json.loads(self._state_path.read_text())
        except (OSError, ValueError):
            return {}

    def _save(self, count: int):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._prune(self._clock())
        self._state_path.write_text(json.dumps({"day": self._today(), "count": count,
                                                "recent": list(self._events)}))

    def used_today(self) -> int:
        s = self._load()
        return s.get("count", 0) if s.get("day") == self._today() else 0

    def remaining_today(self) -> int | None:
        return None if self.rpd is None else max(self.rpd - self.used_today(), 0)


    # ---- per-minute window ----
    def _prune(self, now: float):
        while self._events and now - self._events[0][0] >= 60:
            self._events.popleft()

    def _wait_needed(self, now: float, tokens: int) -> float:
        self._prune(now)
        waits = [0.0]
        if self.rpm and len(self._events) >= self.rpm:
            waits.append(60 - (now - self._events[len(self._events) - self.rpm][0]))
        if self.tpm:
            used = sum(t for _, t in self._events)
            excess = used + tokens - self.tpm
            for ts, t in self._events:  # wait until enough old tokens leave the window
                if excess <= 0:
                    break
                excess -= t
                waits.append(60 - (now - ts))
        return max(waits)

    def acquire(self, tokens: int) -> list:
        """Block until a call of `tokens` fits; returns a handle to pass to `record`."""
        if self.tpm and tokens > self.tpm:
            raise QuotaExhausted(f"one call (~{tokens} tokens) exceeds the TPM limit {self.tpm}")
        if self.rpd is not None and self.used_today() >= self.rpd:
            raise QuotaExhausted(f"daily request quota used ({self.used_today()}/{self.rpd}, "
                                 f"resets at midnight {self.tz.key})")
        with self._lock:
            while (w := self._wait_needed(self._clock(), tokens)) > 0:
                self._sleep(w + 0.05)
            handle = [self._clock(), tokens]
            self._events.append(handle)
            self._save(self.used_today() + 1)
            return handle

    def record(self, handle: list, actual_tokens: int | None):
        """Replace the estimate with the provider-reported total (if any)."""
        if actual_tokens:
            with self._lock:
                handle[1] = actual_tokens
                self._save(self.used_today())

    def penalize(self, seconds: float):
        """Provider said 'retry in N s' (429): block the window for that long."""
        with self._lock:
            self._sleep(seconds)


_LIMITERS: dict[str, RateLimiter] = {}


def limiter_for(provider: str, model: str) -> RateLimiter | None:
    """One shared limiter per provider+model, configured from env; None if no limits set."""
    rpm, tpm, rpd = (int(v) if (v := os.getenv(k)) else None
                     for k in ("LLM_RPM", "LLM_TPM", "LLM_RPD"))
    if not (rpm or tpm or rpd):
        return None
    key = f"{provider}_{model}"
    if key not in _LIMITERS:
        tz = os.getenv("LLM_QUOTA_TZ", "America/Los_Angeles" if provider == "gemini" else "UTC")
        _LIMITERS[key] = RateLimiter(rpm, tpm, rpd, key=key, tz=tz,
                                     margin=float(os.getenv("LLM_LIMIT_MARGIN", "0.9")))
    return _LIMITERS[key]
