"""Shared rate-limit-or-raise helper for endpoints outside auth.py.

auth.py keeps its own local limiter instance/wrapper for historical
reasons (login, 2FA) - this module exists so financial-mutation
endpoints added afterwards (merchant withdrawals/invoices, API-key
auth) don't each re-implement the same "check + 429" boilerplate.
"""

from fastapi import HTTPException, status

from app.infra.redis_rate_limiter import RedisRateLimiter

_limiter = RedisRateLimiter()


async def enforce_rate_limit(
    key: str, max_requests: int, window_seconds: int, *, fail_mode: str = "fallback"
) -> None:
    limited = await _limiter.is_rate_limited(
        key, max_requests, window_seconds, fail_mode=fail_mode
    )
    if limited:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many requests, try again later",
            headers={"Retry-After": str(window_seconds)},
        )
