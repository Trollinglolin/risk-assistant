# Security

## Threat model

| Asset | Threat | Control |
|---|---|---|
| LLM provider key (paid quota) | Leak via repo, image or logs | Only in `.env` (gitignored) locally. In the cloud: Azure Container Apps secrets (`infra/azure/deploy.sh`) or AWS SSM SecureString loaded at cold start (`src/hkrisk/ssm.py`). Never in the image, Lambda env config or logs. CI runs gitleaks on every push. |
| `/agent/ask` (spends LLM quota) | Anonymous abuse, key guessing | `X-API-Key` required. Keys shorter than 24 characters or known placeholders disable the endpoint (fail closed). Constant-time comparison against every configured key. Per-key rate limit, logged by SHA-256 fingerprint, never the key. |
| Compute (Lambda bill) | Request floods on unauthenticated risk endpoints (a GARCH backtest costs about 1 s of CPU) | Per-client rate limit on every route except `/health`. Bounded query parameters (window ≤ 3000, horizon ≤ 10, years ≤ 20). Reserved concurrency on the API function. Budget alert. |
| Agent tool layer | Prompt injection steering tool calls | 9 tools, all **read-only** (no writes, network, shell or file access). Deny-by-default JSON Schema validation (`additionalProperties: false`) before any engine code runs. Tool results contain only engine numbers and local YAML text, never third-party content. At most 8 tool rounds and 2,048 output tokens per turn. The grounding eval measures injected or invented numbers (`h11`, `h12` in `evals/questions.yaml`). |
| Audit trail | Silent misuse | One `hkrisk.audit` log line per tool call (tool, argument hash, error flag) and per agent request (key fingerprint, client IP, tools, tokens, latency). The question text is not logged. |
| Browser | XSS, clickjacking, key theft | Dashboard and API share one origin. A strict CSP is sent on every page (`script-src 'self'`, no inline scripts, `connect-src 'self'`, `frame-ancestors 'none'`). React escapes all model output; there is no raw HTML rendering. The agent key is entered by the user into `sessionStorage` only, and in local dev the Vite proxy injects it server-side. API responses send `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, and HSTS over HTTPS. CORS is off unless `HKRISK_CORS_ORIGINS` lists explicit origins. The app sends the CSP itself; when the dashboard is hosted separately (S3/CloudFront), set the equivalent policy there (`infra/deploy.md`). |
| Supply chain | Compromised action or dependency | GitHub Actions pinned to full commit SHAs, with a read-only `GITHUB_TOKEN` and `persist-credentials: false`. Workflow inputs pass through env vars, not script interpolation. `uv.lock` and `package-lock.json` are committed and installed with `--locked` / `npm ci --ignore-scripts`. CI runs `pip-audit` and `npm audit`. |
| Container | Escalation, tampering | Runs as uid 10001. Works on a read-only root filesystem with only `/tmp` writable (tested with `docker run --read-only --tmpfs /tmp`). No server banner. `/docs` is off unless `HKRISK_DOCS=1`. |

## Configuration

| Variable | Purpose |
|---|---|
| `HKRISK_API_KEY` / `HKRISK_API_KEYS` | Agent key, or comma-separated keys during rotation. Generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `HKRISK_SSM_PREFIX` | Load secrets from SSM at startup (e.g. `/hkrisk`) |
| `HKRISK_RATE_LIMIT_PER_MIN` | Agent calls per key per minute (default 10) |
| `HKRISK_IP_RATE_LIMIT_PER_MIN` | Requests per client per minute, all routes (default 120) |
| `HKRISK_TRUST_PROXY` | `1` behind exactly one proxy: the client IP is taken from the last `X-Forwarded-For` hop |
| `HKRISK_CORS_ORIGINS` | Allowed browser origins (unset = none) |
| `HKRISK_DOCS` | `0` hides `/docs` and `/openapi.json` |

## Known limitations

- Rate limits are in-memory, so they apply per instance. Reserved concurrency bounds the total;
  use API Gateway usage plans or WAF for stronger guarantees.
- There is one shared agent key, with no per-user identity. That is fine for a demo or
  portfolio deployment; put a real identity provider in front for multi-user use.
- `evals/run_eval.py` evaluates expressions from `evals/questions.yaml` with builtins disabled. Treat
  that file as code and review changes to it.

## Reporting

Please report vulnerabilities privately through GitHub's "Report a vulnerability" (Security tab)
rather than in a public issue.
