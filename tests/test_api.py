import pytest
from fastapi.testclient import TestClient

from hkrisk.api.main import app
from hkrisk.service import RiskService


@pytest.fixture(scope="module")
def client(snapshot, holdings):
    with TestClient(app) as c:
        core = RiskService(snapshot, holdings)  # committed data, no network
        app.state.services = {"core": core, "hsi": core}
        yield c


AUDIT = {"as_of", "method", "currency"}


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_portfolio(client):
    r = client.get("/portfolio").json()
    assert r["currency"] == "HKD" and len(r["positions"]) == 9
    assert sum(p["value"] for p in r["positions"]) == pytest.approx(r["total_value"])


@pytest.mark.parametrize("method", ["historical", "normal", "t", "garch", "evt"])
def test_var_methods(client, method):
    r = client.get("/risk/var", params={"method": method, "alpha": 0.99}).json()
    assert AUDIT <= r.keys() and r["method"] == method and r["var"] > 0


def test_var_as_of(client):
    r = client.get("/risk/var", params={"as_of": "2024-06-28"}).json()
    assert r["as_of"] == "2024-06-28"


@pytest.mark.parametrize("params", [{"alpha": 1.5}, {"method": "magic"}, {"window": 5},
                                    {"as_of": "2030-01-01"}])
def test_bad_input_422(client, params):
    assert client.get("/risk/var", params=params).status_code == 422


def test_contributions(client):
    r = client.get("/risk/contributions", params={"measure": "es"}).json()
    assert AUDIT <= r.keys()
    assert sum(c["component"] for c in r["components"]) == pytest.approx(r["total"])
    assert client.get("/risk/contributions", params={"method": "garch"}).status_code == 422


def test_explain_change(client):
    r = client.get("/risk/explain-change").json()
    assert AUDIT <= r.keys() and "window_roll_effect" in r


def test_compare(client):
    r = client.get("/risk/compare").json()
    assert len(r["ranked_by_var_desc"]) == 5


def test_stress(client):
    assert len(client.get("/stress/scenarios").json()["scenarios"]) == 3
    r = client.get("/stress/gfc_2008").json()
    assert AUDIT <= r.keys() and r["proxied"]
    assert client.get("/stress/nope").status_code == 422
    r = client.get("/stress/hsi-shock", params={"shock": -0.2}).json()
    assert r["total_pnl"] < 0 and AUDIT <= r.keys()


def test_backtest(client):
    r = client.get("/backtest", params={"method": "historical", "years": 5}).json()
    assert AUDIT <= r.keys() and r["days"] >= 1200


STRONG = "k" * 8 + "Zq3vT8pLw2xN9rB4mD7s"


def test_agent_requires_key(client, monkeypatch):
    monkeypatch.delenv("HKRISK_API_KEYS", raising=False)
    monkeypatch.setenv("HKRISK_API_KEY", STRONG)
    assert client.post("/agent/ask", json={"question": "VaR?"}).status_code == 401
    assert client.post("/agent/ask", json={"question": "VaR?"},
                       headers={"X-API-Key": "wrong"}).status_code == 401


@pytest.mark.parametrize("weak", ["change-me", "short-key"])
def test_weak_configured_key_fails_closed(client, monkeypatch, weak):
    monkeypatch.delenv("HKRISK_API_KEYS", raising=False)
    monkeypatch.setenv("HKRISK_API_KEY", weak)
    r = client.post("/agent/ask", json={"question": "VaR?"}, headers={"X-API-Key": weak})
    assert r.status_code == 503 and "too weak" in r.json()["detail"]


def test_key_rotation_accepts_any_listed_key(client, monkeypatch):
    from hkrisk.api.main import require_key

    old, new = STRONG, STRONG[::-1]
    monkeypatch.setenv("HKRISK_API_KEYS", f"{old}, {new}")
    assert require_key(old) != require_key(new)  # both valid, distinct fingerprints
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as e:
        require_key("k" * 28)
    assert e.value.status_code == 401


def test_security_headers(client):
    h = client.get("/health").headers
    assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY"


def test_ip_rate_limit(client, monkeypatch):
    import hkrisk.api.main as m

    monkeypatch.setattr(m, "IP_LIMIT", 3)
    m._ip_hits.clear()
    codes = [client.get("/stress/scenarios").status_code for _ in range(5)]
    assert codes[:3] == [200] * 3 and codes[3:] == [429, 429]
    assert client.get("/health").status_code == 200  # health checks are never limited
    m._ip_hits.clear()


def test_backtest_series(client):
    r = client.get("/backtest/series", params={"method": "historical", "years": 2})
    assert r.status_code == 200
    j = r.json()
    n = len(j["dates"])
    assert n >= 250 and len(j["var"]) == len(j["loss"]) == len(j["exception"]) == n
    assert sum(j["exception"]) == sum(l > v for l, v in zip(j["loss"], j["var"]))
    assert j["currency"] == "HKD" and j["as_of"]


def test_portfolio_switch_and_validation(client):
    assert client.get("/portfolio", params={"portfolio": "core"}).status_code == 200
    assert client.get("/portfolio", params={"portfolio": "nope"}).status_code == 422


def test_ssm_loader_only_sets_allowlisted_names(monkeypatch):
    from hkrisk.ssm import load_ssm_env

    class FakeSSM:
        def get_paginator(self, _):
            return self

        def paginate(self, **kw):
            assert kw["WithDecryption"] and kw["Path"] == "/hkrisk"
            yield {"Parameters": [{"Name": "/hkrisk/GEMINI_API_KEY", "Value": "g"},
                                  {"Name": "/hkrisk/PATH", "Value": "/evil"}]}

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert load_ssm_env("/hkrisk/", client=FakeSSM()) == ["GEMINI_API_KEY"]
    import os
    assert os.environ["GEMINI_API_KEY"] == "g" and os.environ.get("PATH") != "/evil"
