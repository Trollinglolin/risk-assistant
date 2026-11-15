from datetime import datetime

import pytest

from hkrisk.agent.ratelimit import QuotaExhausted, RateLimiter, estimate_tokens


class FakeTime:
    def __init__(self):
        self.t = 0.0
        self.slept = 0.0

    def clock(self):
        return self.t

    def sleep(self, s):
        self.t += s
        self.slept += s


def make(tmp_path, ft, **kw):
    return RateLimiter(key="test", margin=1.0, state_dir=tmp_path, clock=ft.clock,
                       sleep=ft.sleep, now=lambda: datetime(2026, 11, 15), **kw)


def test_rpm_spaces_requests(tmp_path):
    ft = FakeTime()
    lim = make(tmp_path, ft, rpm=3)
    for _ in range(3):
        lim.acquire(10)
    assert ft.slept == 0
    lim.acquire(10)  # 4th within a minute must wait for the 1st to age out
    assert ft.t >= 60


def test_tpm_waits_for_old_tokens(tmp_path):
    ft = FakeTime()
    lim = make(tmp_path, ft, tpm=10_000)
    h = lim.acquire(6_000)
    lim.record(h, 8_000)  # actual usage replaces the estimate
    ft.t = 10
    lim.acquire(3_000)  # 8k + 3k > 10k -> wait until t=60
    assert ft.t >= 60
    with pytest.raises(QuotaExhausted):
        lim.acquire(20_000)  # can never fit


def test_daily_quota_persists_and_stops(tmp_path):
    ft = FakeTime()
    lim = make(tmp_path, ft, rpd=2)
    lim.acquire(1)
    lim.acquire(1)
    again = make(tmp_path, ft, rpd=2)  # new process, same day: count was saved
    assert again.remaining_today() == 0
    with pytest.raises(QuotaExhausted):
        again.acquire(1)
    tomorrow = RateLimiter(rpd=2, key="test", margin=1.0, state_dir=tmp_path,
                           now=lambda: datetime(2026, 11, 16))
    assert tomorrow.remaining_today() == 2


def test_margin_and_estimate():
    assert RateLimiter(rpm=15, tpm=250_000, rpd=500).rpd == 450
    assert estimate_tokens("x" * 3000) == 2000


def test_minute_window_shared_across_processes(tmp_path):
    ft = FakeTime()
    first = make(tmp_path, ft, rpm=2)
    first.acquire(1)
    first.acquire(1)
    second = make(tmp_path, ft, rpm=2)  # e.g. the full eval started right after a smoke test
    second.acquire(1)
    assert ft.t >= 60
