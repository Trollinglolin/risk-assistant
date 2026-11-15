"""FastAPI service. Thin: validate -> call RiskService -> return. No maths here."""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Literal

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from hkrisk.agent.ratelimit import QuotaExhausted
from hkrisk.service import PORTFOLIOS, RiskService, get_service
from hkrisk.ssm import load_ssm_env

Method = Literal["historical", "normal", "t", "garch", "evt"]
Alpha = Query(0.99, gt=0.5, lt=1.0, description="confidence level, e.g. 0.99")
Window = Query(500, ge=50, le=3000)


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_ssm_env()  # no-op unless HKRISK_SSM_PREFIX is set (Lambda)
    # load every book once at startup; tests replace app.state.services
    app.state.services = {name: get_service(name) for name in PORTFOLIOS}
    yield


load_dotenv()  # HKRISK_API_KEY, LLM_* settings from the repo .env (real env vars win)

log = logging.getLogger("hkrisk.audit")
_hk = logging.getLogger("hkrisk")  # uvicorn only configures its own loggers
if not _hk.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    _hk.addHandler(_h)
    _hk.setLevel(os.getenv("HKRISK_LOG_LEVEL", "INFO"))
_docs = os.getenv("HKRISK_DOCS", "1") != "0"  # set 0 to hide /docs and /openapi.json
app = FastAPI(title="HK Market-Risk Assistant", version="0.1.0", lifespan=lifespan,
              docs_url="/docs" if _docs else None, redoc_url=None,
              openapi_url="/openapi.json" if _docs else None)
# Browser origins allowed to call the API (the dashboard when hosted elsewhere, e.g. S3).
# Comma-separated; unset = same-origin only (local dev goes through the Vite proxy).
if origins := [o.strip() for o in os.getenv("HKRISK_CORS_ORIGINS", "").split(",") if o.strip()]:
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"],
                       allow_headers=["X-API-Key", "Content-Type"])

# ---- per-client rate limit for every route (the risk endpoints are unauthenticated and some,
# like a GARCH backtest, cost seconds of CPU). In-memory, so per instance: on Lambda also cap
# reserved concurrency (infra/deploy.md). Behind exactly one trusted proxy (Lambda Function
# URL, ALB, CloudFront) set HKRISK_TRUST_PROXY=1: the client IP is then the LAST
# X-Forwarded-For hop, the one the proxy appended. Earlier hops are client-controlled.
IP_LIMIT = int(os.getenv("HKRISK_IP_RATE_LIMIT_PER_MIN", "120"))
# The dashboard is same-origin with the API, has no inline scripts and loads nothing external.
# Recharts sets inline style attributes, hence 'unsafe-inline' for styles only.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; "
       "base-uri 'self'; form-action 'self'; frame-ancestors 'none'")
_ip_hits: dict[str, deque] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    if os.getenv("HKRISK_TRUST_PROXY") == "1":
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


@app.middleware("http")
async def guard(request: Request, call_next):
    if request.url.path != "/health":
        q, now = _ip_hits[_client_ip(request)], time.time()
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= IP_LIMIT:
            return JSONResponse(status_code=429, content={"detail": "rate limit exceeded"},
                                headers={"Retry-After": "60"})
        q.append(now)
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    path = request.url.path
    if not path.startswith(("/docs", "/redoc")):  # Swagger UI loads from a CDN
        resp.headers["Content-Security-Policy"] = CSP
    if path.startswith("/agent"):
        resp.headers["Cache-Control"] = "no-store"
    elif path.startswith("/assets/"):  # content-hashed dashboard bundles
        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    else:
        resp.headers["Cache-Control"] = "public, max-age=300"
    if request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https":
        resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return resp


Portfolio = Literal["core", "hsi"]


def svc(request: Request,
        portfolio: Portfolio = Query("core", description="core (9 names) or hsi (95)"),
        ) -> RiskService:
    return request.app.state.services[portfolio]


@app.exception_handler(QuotaExhausted)
async def quota_handler(request: Request, exc: QuotaExhausted):
    return JSONResponse(status_code=429, content={"detail": f"LLM quota: {exc}"})


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.get("/health")
def health(s: RiskService = Depends(svc)):
    return {"status": "ok", "latest_data_date": s.latest}


@app.get("/portfolio")
def portfolio(as_of: str | None = None, s: RiskService = Depends(svc)):
    return s.portfolio(as_of)


@app.get("/risk/var")
def risk_var(method: Method = "historical", alpha: float = Alpha, window: int = Window,
             as_of: str | None = None, horizon_days: int = Query(1, ge=1, le=10),
             s: RiskService = Depends(svc)):
    return s.var(method, alpha, window, as_of, horizon_days)


@app.get("/risk/compare")
def risk_compare(alpha: float = Alpha, window: int = Window, as_of: str | None = None,
                 s: RiskService = Depends(svc)):
    return s.compare_methods(alpha, window, as_of)


@app.get("/risk/contributions")
def risk_contributions(method: Literal["historical", "normal"] = "historical",
                       measure: Literal["var", "es"] = "var", alpha: float = Alpha,
                       window: int = Window, as_of: str | None = None,
                       s: RiskService = Depends(svc)):
    r = s.contributions(method, measure, alpha, window, as_of)
    return r


@app.get("/risk/explain-change")
def risk_explain_change(start: str | None = None, end: str | None = None,
                        method: Literal["historical", "normal"] = "historical",
                        alpha: float = Alpha, window: int = Window,
                        s: RiskService = Depends(svc)):
    return s.explain_change(start, end, method, alpha, window)


@app.get("/stress/scenarios")
def stress_list(s: RiskService = Depends(svc)):
    return s.scenarios()


@app.get("/stress/hsi-shock")
def stress_hsi(shock: float = Query(..., ge=-0.9, le=0.9), as_of: str | None = None,
               s: RiskService = Depends(svc)):
    return {**s.hsi_shock(shock, as_of), "method": "beta_to_hsi"}


@app.get("/stress/{scenario}")
def stress_run(scenario: str, as_of: str | None = None, s: RiskService = Depends(svc)):
    return {**s.stress(scenario, as_of), "method": "historical_scenario"}


@app.get("/backtest/series")
def backtest_series(method: Method = "historical", years: float | None = Query(None, gt=0, le=20),
                    alpha: float = Alpha, window: int = Window, s: RiskService = Depends(svc)):
    return s.backtest_series(method, years, alpha, window)


@app.get("/backtest")
def backtest(method: Method = "historical", years: float | None = Query(None, gt=0, le=20),
             alpha: float = Alpha, window: int = Window, s: RiskService = Depends(svc)):
    return s.backtest(method, years, alpha, window)


# ---------------- agent (protected) ----------------

_hits: dict[str, deque] = defaultdict(deque)
RATE_LIMIT = int(os.getenv("HKRISK_RATE_LIMIT_PER_MIN", "10"))


WEAK_KEYS = {"", "change-me", "changeme", "test", "secret", "password"}
MIN_KEY_LEN = 24


def _configured_keys() -> list[str]:
    """HKRISK_API_KEYS (comma-separated, for rotation) or HKRISK_API_KEY."""
    raw = os.getenv("HKRISK_API_KEYS") or os.getenv("HKRISK_API_KEY") or ""
    return [k.strip() for k in raw.split(",") if k.strip()]


def key_fingerprint(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:10]


def require_key(x_api_key: str | None = Header(default=None)) -> str:
    keys = _configured_keys()
    if not keys:
        raise HTTPException(503, "agent endpoint disabled: HKRISK_API_KEY not configured")
    if any(k.lower() in WEAK_KEYS or len(k) < MIN_KEY_LEN for k in keys):
        # fail closed rather than serve a guessable key; generate one with
        # python -c "import secrets; print(secrets.token_urlsafe(32))"
        raise HTTPException(503, "agent endpoint disabled: HKRISK_API_KEY is too weak "
                                 f"(need >= {MIN_KEY_LEN} random characters)")
    # compare against every configured key (no early exit) in constant time
    supplied = (x_api_key or "").encode()
    ok = False
    for k in keys:
        ok |= secrets.compare_digest(supplied, k.encode())
    if not x_api_key or not ok:
        raise HTTPException(401, "missing or invalid X-API-Key")
    fp = key_fingerprint(x_api_key)  # rate-limit and log by fingerprint, never the key
    q, now = _hits[fp], time.time()
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= RATE_LIMIT:
        raise HTTPException(429, "rate limit exceeded")
    q.append(now)
    return fp


class AskRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=2000)
    portfolio: Portfolio = "core"


@app.post("/agent/ask")
def agent_ask(req: AskRequest, request: Request, key_fp: str = Depends(require_key)):
    from hkrisk.agent.loop import ask

    r = ask(req.question, service=request.app.state.services[req.portfolio])
    # audit trail: who (key fingerprint), what tools, outcome. The question text is not logged.
    log.info("agent_ask key=%s ip=%s portfolio=%s q_len=%d tools=%s errors=%d iters=%d "
             "tokens=%d+%d latency=%.2fs", key_fp, _client_ip(request), req.portfolio,
             len(req.question), [c.name for c in r.tool_calls],
             sum(c.is_error for c in r.tool_calls), r.iterations, r.input_tokens,
             r.output_tokens, r.latency_s)
    return r.to_dict()


# ---------------- dashboard (same origin) ----------------
# When HKRISK_STATIC_DIR points at the built dashboard (dashboard/dist, baked into the
# container image), serve it at "/". Registered last so every API route above wins.
_static = os.getenv("HKRISK_STATIC_DIR")
if _static and os.path.isdir(_static):
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=_static, html=True), name="dashboard")
