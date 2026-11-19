# Two images from one build (the `api` image runs on Azure Container Apps or AWS Lambda; `report` is Lambda-only):
#   docker build --target api    -t hkrisk-api .     (FastAPI via AWS Lambda Web Adapter)
#   docker build --target report -t hkrisk-report .  (plain Lambda handler hkrisk.report.handler)
# No secrets are baked in: LLM keys and HKRISK_API_KEY come from SSM / Secrets Manager at run
# time (infra/deploy.md). Lambda's filesystem is read-only except /tmp, so every cache points
# there.
# ---- dashboard: static build, served same-origin by the API image ----
FROM node:22-bookworm-slim AS dashboard
WORKDIR /dash
COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY dashboard/ ./
# empty API base = same origin as the page
RUN VITE_API_BASE= npm run build

FROM python:3.12-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    HOME=/tmp XDG_CACHE_HOME=/tmp/.cache MPLCONFIGDIR=/tmp/mpl HKRISK_QUOTA_DIR=/tmp/hkrisk
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project
COPY src/ src/
COPY portfolio.yaml scenarios.yaml ./
COPY portfolios/ portfolios/
COPY universe/ universe/
COPY data/snapshot_2026-10-30.parquet data/snapshot_hsi_2026-10-30.parquet data/
RUN uv sync --locked --no-dev \
 && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app

FROM base AS api
# The Lambda Web Adapter is inert outside Lambda; the same image runs on Azure Container Apps.
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:0.9.1 /lambda-adapter /opt/extensions/lambda-adapter
COPY --from=dashboard /dash/dist /app/web
# behind the platform proxy: trust its X-Forwarded-For hop; hide /docs unless HKRISK_DOCS=1
ENV PORT=8080 AWS_LWA_READINESS_CHECK_PATH=/health HKRISK_TRUST_PROXY=1 HKRISK_DOCS=0 \
    HKRISK_STATIC_DIR=/app/web
USER 10001
CMD ["uvicorn", "hkrisk.api.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-server-header"]

FROM base AS report
RUN uv pip install --python /app/.venv/bin/python awslambdaric
USER 10001
ENTRYPOINT ["python", "-m", "awslambdaric"]
CMD ["hkrisk.report.handler"]
