"""
Centralised async Redis client for GIGVEYRO.

Usage:
    from app.infra.redis_client import get_redis, close_redis, redis_health_check

Startup/shutdown wiring (main.py lifespan):
    await init_redis()
    ...
    await close_redis()

The module exposes a module-level singleton pool.
All callers share the same connection pool — no reconnect overhead per request.
"""
from __future__ import annotations

import asyncio
import logging

import redis.asyncio as aioredis
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import settings

logger = logging.getLogger(__name__)

# Module-level Redis pool singleton
_redis_pool: Redis | None = None


async def init_redis() -> None:
    """Initialise the shared Redis connection pool.

    Call once at application startup (lifespan).
    Retries with backoff to handle Redis not-yet-ready in Docker.
    """
    global _redis_pool  # noqa: PLW0603

    max_attempts = 6
    for attempt in range(1, max_attempts + 1):
        try:
            pool = aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                max_connections=settings.REDIS_MAX_CONNECTIONS,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True,
                health_check_interval=30,
            )
            # Validate connectivity
            await pool.ping()
            _redis_pool = pool
            logger.info("Redis connected: %s", settings.REDIS_URL.split("@")[-1])
            return
        except RedisError as exc:
            if attempt < max_attempts:
                wait = 2 ** attempt
                logger.warning(
                    "Redis connection attempt %d/%d failed (%s). Retrying in %ds...",
                    attempt,
                    max_attempts,
                    exc,
                    wait,
                )
                await asyncio.sleep(wait)
            else:
                logger.error("Redis unavailable after %d attempts: %s", max_attempts, exc)
                raise


async def close_redis() -> None:
    """Close the shared Redis connection pool. Call at application shutdown."""
    global _redis_pool  # noqa: PLW0603
    if _redis_pool is not None:
        await _redis_pool.aclose()
        _redis_pool = None
        logger.info("Redis connection pool closed.")


def get_redis() -> Redis:
    """Return the shared Redis client.

    Raises RuntimeError if init_redis() was not called.
    """
    if _redis_pool is None:
        raise RuntimeError(
            "Redis pool not initialised. "
            "Ensure init_redis() is called in the application lifespan."
        )
    return _redis_pool


async def redis_health_check() -> dict[str, str]:
    """Returns health status dict. Safe to call from /health/ready.

    Never raises — returns error state instead.
    """
    try:
        client = get_redis()
        latency_ms = await _ping_with_latency(client)
        return {"status": "ok", "latency_ms": f"{latency_ms:.1f}"}
    except RuntimeError:
        return {"status": "not_initialised"}
    except RedisError as exc:
        logger.warning("Redis health check failed: %s", exc)
        return {"status": "error", "detail": str(exc)}


async def _ping_with_latency(client: Redis) -> float:
    import time

    t0 = time.monotonic()
    await client.ping()
    return (time.monotonic() - t0) * 1000
