# ============================================================
# GIGVEYRO Backend — Production Dockerfile
# Python 3.11-slim, non-root user, layered deps for cache
# ============================================================

# ---------- Stage 1: dependency resolver ----------
FROM python:3.11-slim AS deps

WORKDIR /build

# Install build tools needed for native extensions (e.g. asyncpg, argon2-cffi)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
        libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./

# Install into a prefix so we can copy cleanly to runner
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---------- Stage 2: runner ----------
FROM python:3.11-slim AS runner

# Runtime deps only (no build tools)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for security
RUN groupadd --gid 1001 appgroup \
    && useradd --uid 1001 --gid appgroup --no-create-home appuser

WORKDIR /app

# Copy installed packages from deps stage
COPY --from=deps /install /usr/local

# Copy application code — no .env, no .venv, no __pycache__
COPY --chown=appuser:appgroup . .

# Drop to non-root
USER appuser

# Expose API port
EXPOSE 8000

# -------------------------------------------------------
# CMD notes:
#
# For WebSocket correctness with InMemoryRealtimeBroker,
# we default to a SINGLE uvicorn process.
# When switching to RedisBroker (horizontal scaling),
# increase WEB_CONCURRENCY.
#
# SIGTERM is forwarded correctly by uvicorn for graceful shutdown.
# -------------------------------------------------------
ENV WEB_CONCURRENCY=1
ENV FORWARDED_ALLOW_IPS=127.0.0.1
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health/live || exit 1

CMD ["sh", "-c", \
    "uvicorn app.main:app \
     --host 0.0.0.0 \
     --port 8000 \
     --workers ${WEB_CONCURRENCY} \
     --proxy-headers \
     --forwarded-allow-ips ${FORWARDED_ALLOW_IPS} \
     --log-level ${LOG_LEVEL:-info} \
     --no-access-log"]
