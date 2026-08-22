"""
Tests for Redis infrastructure components.

Tests:
  - Redis client init / health check behavior
  - Unavailable Redis graceful fallback
  - Distributed lock acquire/release
  - Redis rate limiter behavior when Redis unavailable
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.infra.redis_client import redis_health_check


class TestRedisHealthCheck:
    """redis_health_check returns structured response in all scenarios."""

    async def test_returns_not_initialised_when_no_pool(self):
        """Health check returns 'not_initialised' when Redis pool is not up."""
        with patch("app.infra.redis_client._redis_pool", None):
            result = await redis_health_check()
        assert result["status"] == "not_initialised"

    async def test_returns_ok_when_ping_succeeds(self):
        """Health check returns 'ok' when Redis responds to ping."""
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)

        with patch("app.infra.redis_client._redis_pool", mock_redis):
            result = await redis_health_check()

        assert result["status"] == "ok"
        assert "latency_ms" in result

    async def test_returns_error_on_connection_failure(self):
        """Health check returns 'error' dict (does not raise) on Redis failure."""
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(side_effect=RedisConnectionError("refused"))

        with patch("app.infra.redis_client._redis_pool", mock_redis):
            result = await redis_health_check()

        assert result["status"] == "error"
        assert "detail" in result


class TestDistributedLock:
    """DistributedLock acquire/release behavior."""

    async def test_lock_acquired_when_key_free(self):
        """Lock is acquired when Redis key does not exist."""
        from app.workers.distributed_lock import DistributedLock

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)  # SET NX succeeded
        mock_redis.eval = AsyncMock(return_value=1)  # Release succeeded

        async with DistributedLock(mock_redis, "test_lock", ttl_ms=5000) as acquired:
            assert acquired is True

        mock_redis.set.assert_called_once()
        # Verify SET NX PX was used (not plain SET)
        call_kwargs = mock_redis.set.call_args.kwargs
        assert call_kwargs.get("nx") is True
        assert call_kwargs.get("px") == 5000

    async def test_lock_not_acquired_when_held(self):
        """Lock returns False when another holder has the key."""
        from app.workers.distributed_lock import DistributedLock

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=None)  # SET NX failed (key exists)

        async with DistributedLock(mock_redis, "held_lock", ttl_ms=5000) as acquired:
            assert acquired is False

        # Release should NOT be called if we didn't acquire
        mock_redis.eval.assert_not_called()

    async def test_lock_released_on_exception(self):
        """Lock is released even if the protected code raises."""
        from app.workers.distributed_lock import DistributedLock

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.eval = AsyncMock(return_value=1)

        with pytest.raises(ValueError):
            async with DistributedLock(mock_redis, "exc_lock", ttl_ms=5000) as acquired:
                assert acquired is True
                raise ValueError("test error")

        # Lock must be released despite exception
        mock_redis.eval.assert_called_once()


class TestRedisRateLimiter:
    """RedisRateLimiter fail-open behavior when Redis unavailable."""

    async def test_allows_request_when_redis_not_initialised(self):
        """Rate limiter fails open (allows) when Redis pool is not ready."""
        from app.infra.redis_rate_limiter import RedisRateLimiter

        limiter = RedisRateLimiter()

        with patch("app.infra.redis_rate_limiter.get_redis", side_effect=RuntimeError("not init")):
            result = await limiter.is_rate_limited("test:key", max_requests=1, window_seconds=60)

        # Fail-open: allow the request
        assert result is False

    async def test_allows_request_on_redis_error(self):
        """Rate limiter fails open on Redis connection error."""
        from app.infra.redis_rate_limiter import RedisRateLimiter

        limiter = RedisRateLimiter()
        mock_redis = AsyncMock()
        mock_redis.script_load = AsyncMock(return_value="sha1hash")
        mock_redis.evalsha = AsyncMock(side_effect=RedisConnectionError("timeout"))

        with patch("app.infra.redis_rate_limiter.get_redis", return_value=mock_redis):
            limiter._script_sha = "sha1hash"
            result = await limiter.is_rate_limited("test:key", max_requests=5, window_seconds=60)

        # Fail-open: allow the request
        assert result is False

    async def test_fails_closed_on_redis_error(self):
        """Rate limiter fails closed (blocks / returns True) when mode is 'closed'."""
        from app.infra.redis_rate_limiter import RedisRateLimiter

        limiter = RedisRateLimiter()

        with (
            patch("app.infra.redis_rate_limiter.get_redis", side_effect=RuntimeError("not init")),
            patch("app.core.config.settings.RATE_LIMIT_FAIL_MODE", "closed"),
        ):
            result = await limiter.is_rate_limited("test:key", max_requests=1, window_seconds=60)

        # Fail-closed: block the request
        assert result is True

    async def test_falls_back_on_redis_error(self):
        """Rate limiter falls back to local in-memory rate limiter when mode is 'fallback'."""
        from app.infra.redis_rate_limiter import RedisRateLimiter

        limiter = RedisRateLimiter()

        with (
            patch("app.infra.redis_rate_limiter.get_redis", side_effect=RuntimeError("not init")),
            patch("app.core.config.settings.RATE_LIMIT_FAIL_MODE", "fallback"),
        ):
            # 1st request should be allowed
            res1 = await limiter.is_rate_limited(
                "test:fallback_key", max_requests=1, window_seconds=60
            )
            assert res1 is False

            # 2nd request should be blocked
            res2 = await limiter.is_rate_limited(
                "test:fallback_key", max_requests=1, window_seconds=60
            )
            assert res2 is True
