"""
Redis distributed lock for singleton background jobs.

Prevents multiple worker instances from running the same singleton job
concurrently (e.g. deposit scanner, deal expiry, cleanup).

Design:
  - Redis SET NX PX (atomic acquire)
  - Owner token prevents foreign release
  - TTL prevents indefinite lock hold on worker crash
  - Context manager for clean usage

Usage:
    async with DistributedLock(redis_client, "deposit_scanner", ttl_ms=60_000) as acquired:
        if not acquired:
            return  # Another worker holds the lock
        await do_work()
"""

from __future__ import annotations

import logging
import secrets
from types import TracebackType

from redis.asyncio import Redis

from app.core.config import settings

logger = logging.getLogger(__name__)

# Lua script for safe release: only release if we own the lock
_RELEASE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
else
    return 0
end
"""


class DistributedLock:
    """Async context manager for a Redis-based distributed lock.

    Args:
        redis:    Async Redis client instance
        name:     Lock name (namespaced by environment and prefixed with 'dlock:')
        ttl_ms:   Lock TTL in milliseconds. Lock auto-releases after this
                  time even if the holder crashes. Choose conservatively.
    """

    def __init__(self, redis: Redis, name: str, ttl_ms: int = 30_000) -> None:
        self._redis = redis
        self._key = f"{settings.REDIS_KEY_PREFIX}:dlock:{name}"
        self._ttl_ms = ttl_ms
        self._token: str | None = None
        self._acquired = False

    async def __aenter__(self) -> bool:
        self._token = secrets.token_hex(16)
        # SET key token NX PX ttl_ms
        result = await self._redis.set(self._key, self._token, nx=True, px=self._ttl_ms)
        self._acquired = result is not None
        if not self._acquired:
            logger.debug("Distributed lock %r already held by another worker.", self._key)
        return self._acquired

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._acquired and self._token:
            try:
                await self._redis.eval(_RELEASE_SCRIPT, 1, self._key, self._token)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to release distributed lock %r: %s", self._key, exc)
