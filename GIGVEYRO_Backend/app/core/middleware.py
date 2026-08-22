import time
import uuid
from collections import defaultdict

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.infra.redis_rate_limiter import RedisRateLimiter


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class RateLimiter:
    def __init__(self):
        self._hits: dict[str, list[float]] = defaultdict(list)

    def is_rate_limited(self, key: str, max_requests: int, window_seconds: int) -> bool:
        now = time.time()
        cutoff = now - window_seconds
        timestamps = [ts for ts in self._hits[key] if ts > cutoff]
        self._hits[key] = timestamps

        if len(timestamps) >= max_requests:
            return True

        self._hits[key].append(now)
        return False


in_memory_rate_limiter = RateLimiter()

# Login is an auth-critical endpoint: a fully-open fail policy would mean a
# Redis outage silently disables brute-force protection. "fallback" keeps a
# bounded local sliding-window limiter enforcing the same numbers in that
# case rather than going fully open or fully closed (which would lock out
# every user - an availability risk of its own) - see SECURITY.md.
_LOGIN_RATE_LIMIT_FAIL_MODE = "fallback"
_login_rate_limiter = RedisRateLimiter()


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        client_ip = request.client.host if request.client else "127.0.0.1"
        path = request.url.path

        if path == "/auth/login" and request.method == "POST":
            key = f"login:{client_ip}"
            limited = await _login_rate_limiter.is_rate_limited(
                key,
                settings.LOGIN_RATE_LIMIT_REQUESTS,
                settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS,
                fail_mode=_LOGIN_RATE_LIMIT_FAIL_MODE,
            )
            if limited:
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={"detail": "Too many login attempts. Please try again later."},
                    headers={"Retry-After": str(settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS)},
                )

        return await call_next(request)
