"""
Health check endpoints for GIGVEYRO.

Endpoints:
  GET /health/db      — Database connectivity (existing)
  GET /health/ready   — Full readiness: DB + Redis
  GET /health/live    — Liveness only (defined in main.py)
  GET /health/diagnostics — Deep provider diagnostics (non-critical path)

Design:
  /health/ready intentionally does NOT check external providers
  (TronGrid, exchange rate API) — transient external outage should NOT
  take down the entire service's readiness probe.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.infra.redis_client import redis_health_check

router = APIRouter()


@router.get("/health")
async def health():
    """Simple liveness/status check."""
    return {"status": "ok"}


@router.get("/health/live")
async def health_live():
    """Process liveness probe."""
    return {"status": "alive"}


@router.get("/health/db")
async def health_db(response: Response, db: AsyncSession = Depends(get_db)):
    """Database connectivity check."""
    try:
        await db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "error", "database": "unavailable"}
    return {"status": "ok", "database": "connected"}


@router.get("/health/ready")
async def health_ready(response: Response, db: AsyncSession = Depends(get_db)):
    """Full readiness check: DB + Redis.

    Returns 503 if any critical dependency is unavailable.
    External providers (TronGrid, exchange rate API) are excluded —
    their transient outage should not affect web service readiness.
    """
    checks: dict[str, object] = {}
    is_ready = True

    # Database check
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = {"status": "ok"}
    except SQLAlchemyError:
        checks["database"] = {"status": "error", "detail": "database check failed"}
        is_ready = False

    # Redis check
    redis_status = await redis_health_check()
    checks["redis"] = {key: value for key, value in redis_status.items() if key != "detail"}
    if redis_status.get("status") != "ok" and settings.APP_ENV in {"staging", "production"}:
        # Redis is critical for cross-process realtime, workers and distributed limits.
        is_ready = False

    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unavailable", "checks": checks}

    return {"status": "ready", "checks": checks}


@router.get("/health/diagnostics")
async def health_diagnostics():
    """Deep diagnostics endpoint — non-critical path.

    Returns provider configuration and readiness details.
    NOT a dependency for load balancer health checks.
    Consider protecting this endpoint in production (e.g. internal network only).
    """
    from app.infra.redis_client import get_redis
    from app.services.fiat_rate.runtime import get_fiat_diagnostics
    from app.services.market_data.runtime import get_market_diagnostics
    from app.services.provider_factory import get_provider_diagnostics

    redis_client = get_redis()
    worker_alive = False
    if redis_client:
        try:
            worker_alive = bool(
                await redis_client.exists(f"{settings.REDIS_KEY_PREFIX}:worker:heartbeat")
            )
        except Exception:
            pass

    return {
        "app_env": settings.APP_ENV,
        "payout_enabled": settings.PAYOUT_ENABLED,
        "providers": get_provider_diagnostics(),
        "market_data": await get_market_diagnostics(),
        "fiat_rate": await get_fiat_diagnostics(),
        "redis": await redis_health_check(),
        "docs_enabled": settings.DOCS_ENABLED,
        "rate_limiting": {
            "fail_mode": settings.RATE_LIMIT_FAIL_MODE,
            "prefix": settings.REDIS_KEY_PREFIX,
        },
        "realtime": {
            "broker": settings.REALTIME_BROKER,
        },
        "workers": {
            "worker_alive": worker_alive,
        },
    }
