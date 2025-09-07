# syntax=docker/dockerfile:1.7

# ---- Base image ----
FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System deps (curl for HEALTHCHECK)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# App directory
WORKDIR /app

# Install runtime deps directly (simple project)
# If you later add a requirements.txt, replace this with: COPY requirements.txt . && pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir fastapi uvicorn httpx[http2] gunicorn

# Copy app code
COPY main.py ./

# Non-root user
RUN useradd -m -u 10001 appuser
USER appuser

# Configurable environment (override at runtime as needed)
ENV UPSTREAM_BASE_URL="http://llm.ai-infra.svc.cluster.local/v1" \
    STATIC_API_KEY="" \
    CONNECT_TIMEOUT=5 \
    READ_TIMEOUT=600 \
    MAX_KEEPALIVE=100 \
    MAX_CONNECTIONS=200 \
    RETRY_TIMES=2 \
    PORT=8080

EXPOSE 8080

# Liveness/Readiness
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -fsS http://127.0.0.1:${PORT}/healthz || exit 1

# Start with Gunicorn+Uvicorn workers (HTTP/2 is upstream; this server listens HTTP/1.1)
# Tune -w / --threads per CPU/memory profile; defaults are conservative.
CMD gunicorn main:app \
    -k uvicorn.workers.UvicornWorker \
    -w 2 \
    --threads 8 \
    -b 0.0.0.0:${PORT} \
    --timeout 600
