"""
Redis-backed sliding-window rate limiter for GIGVEYRO.

Thread-safe and process-safe via atomic Lua script on Redis.

Design:
  - Uses a sorted-set per key (zset) where member=UUID, score=timestamp.
  - Atomic Lua script: removes expired entries → counts → decides → records.
  - TTL set on the zset key = window_seconds (auto-expiry on inactivity).

Usage:
    from app.infra.redis_rate_limiter import RedisRateLimiter

    limiter = RedisRateLimiter()
    limited = await limiter.is_rate_limited("login:1.2.3.4", max_requests=5, window_seconds=60)

Interface is intentionally compatible with the existing in-memory RateLimiter
in app.core.middleware, so Claude #2 can swap it without changing middleware logic.
"""
from __future__ import annotations

import logging
import time
import uuid

from redis.exceptions import RedisError

from app.infra.redis_client import get_redis

logger = logging.getLogger(__name__)

# Atomic Lua script — executed as a single Redis command (no TOCTOU race)
_SLIDING_WINDOW_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local max_req = tonumber(ARGV[3])
local member = ARGV[4]
local cutoff = now - window

-- Remove expired entries outside the window
redis.call('ZREMRANGEBYSCORE', key, '-inf', cutoff)

-- Count remaining entries
local count = redis.call('ZCARD', key)

if count >= max_req then
    -- Rate limited — set expiry and return 1 (limited)
    redis.call('EXPIRE', key, window)
    return 1
end

-- Record this request
redis.call('ZADD', key, now, member)
redis.call('EXPIRE', key, window)
return 0
"""


class RedisRateLimiter:
    """Redis sliding-window rate limiter.

    Drop-in replacement for app.core.middleware.RateLimiter.
    Works across multiple processes/instances.
    """

    def __init__(self) -> None:
        self._script_sha: str | None = None
        self._fallback_limiter: object | None = None

    def _get_fallback_limiter(self) -> object:
        if self._fallback_limiter is None:
            from app.core.middleware import RateLimiter
            self._fallback_limiter = RateLimiter()
        return self._fallback_limiter

    async def is_rate_limited(self, key: str, max_requests: int, window_seconds: int) -> bool:
        """Returns True if the key is rate-limited, False if the request is allowed.

        Handles Redis connection errors and uninitialised states by applying
        the policy configured in settings.RATE_LIMIT_FAIL_MODE:
          - "open": Fail open (allow request)
          - "closed": Fail closed (block request / rate limit)
          - "fallback": Fall back to a local in-memory sliding window rate limiter
        """
        from app.core.config import settings

        try:
            client = get_redis()
            now = time.time()
            member = str(uuid.uuid4())

            # Use EVALSHA for performance (script cached in Redis)
            if self._script_sha is None:
                self._script_sha = await client.script_load(_SLIDING_WINDOW_SCRIPT)

            # Apply prefix namespace to the key
            redis_key = f"{settings.REDIS_KEY_PREFIX}:ratelimit:{key}"

            result = await client.evalsha(
                self._script_sha,
                1,  # numkeys
                redis_key,
                str(now),
                str(window_seconds),
                str(max_requests),
                member,
            )
            return bool(result)

        except (RuntimeError, RedisError) as exc:
            logger.warning(
                "Redis rate limiter error for key %r (mode=%s) — handling: %s",
                key,
                settings.RATE_LIMIT_FAIL_MODE,
                exc,
            )
            if settings.RATE_LIMIT_FAIL_MODE == "closed":
                return True
            elif settings.RATE_LIMIT_FAIL_MODE == "fallback":
                fallback = self._get_fallback_limiter()
                # Call synchronous in-memory fallback
                return fallback.is_rate_limited(key, max_requests, window_seconds)
            else:  # "open"
                return False

