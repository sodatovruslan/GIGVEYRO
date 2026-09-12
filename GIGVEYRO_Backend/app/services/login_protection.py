"""Per-account login brute-force protection, layered on top of the existing
per-IP login rate limiter (app/core/middleware.py).

The IP limiter alone doesn't stop an attacker who rotates IPs (a botnet or
a proxy pool) from continuing to guess passwords against one specific
account. This tracks failed attempts per account (by the submitted
username) and imposes a temporary, auto-expiring, progressively longer
lock once a threshold is crossed - never a permanent lock, since an
attacker fully controls which username they submit and must not be able
to weaponize this into a persistent denial-of-service against a real
user's account.

Concurrency-safety comes from a single atomic Lua script (Redis executes
it as one unit), the same approach as app/infra/redis_rate_limiter.py. A
Redis outage falls back to a local in-memory tracker (same philosophy as
app.core.middleware.RateLimiter / RedisRateLimiter's "fallback" mode) so
brute-force protection is never silently disabled - it just stops being
shared across multiple backend processes until Redis recovers.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from redis.exceptions import RedisError

from app.core.config import settings
from app.infra.redis_client import get_redis

logger = logging.getLogger(__name__)

# KEYS[1] = failure counter, KEYS[2] = lock marker
# ARGV[1] = failure window (seconds), ARGV[2] = threshold, ARGV[3] = base
#           lock seconds, ARGV[4] = max lock seconds
_RECORD_FAILURE_SCRIPT = """
local fail_count = redis.call('INCR', KEYS[1])
if fail_count == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
if fail_count >= tonumber(ARGV[2]) then
    local excess = fail_count - tonumber(ARGV[2])
    local lock_seconds = tonumber(ARGV[3]) * (2 ^ excess)
    if lock_seconds > tonumber(ARGV[4]) then
        lock_seconds = tonumber(ARGV[4])
    end
    lock_seconds = math.floor(lock_seconds)
    redis.call('SET', KEYS[2], fail_count, 'EX', lock_seconds)
    return lock_seconds
end
return 0
"""


def _normalize(username: str) -> str:
    # Deliberately case-preserving: account lookups are exact-match
    # (app/repositories/account.py), so tracking the literal submitted
    # string keeps the lockout bucket for a real account aligned with
    # exactly the requests that could actually authenticate as it.
    # Stripped only so leading/trailing whitespace can't spray the
    # failure count across many distinct keys.
    return username.strip()


@dataclass
class _AccountState:
    fail_count: int = 0
    fail_window_expiry: float = 0.0
    lock_expiry: float = 0.0


class _InMemoryAccountLoginGuard:
    """Single-process fallback used only while Redis is unreachable."""

    def __init__(self) -> None:
        self._state: dict[str, _AccountState] = {}

    def is_locked(self, username: str) -> int | None:
        state = self._state.get(_normalize(username))
        if state is None:
            return None
        remaining = state.lock_expiry - time.time()
        return max(1, int(remaining)) if remaining > 0 else None

    def record_failure(self, username: str) -> None:
        now = time.time()
        key = _normalize(username)
        state = self._state.setdefault(key, _AccountState())
        if state.fail_window_expiry <= now:
            state.fail_count = 0
        state.fail_count += 1
        state.fail_window_expiry = now + settings.LOGIN_ACCOUNT_FAIL_WINDOW_SECONDS
        if state.fail_count >= settings.LOGIN_ACCOUNT_LOCK_THRESHOLD:
            excess = state.fail_count - settings.LOGIN_ACCOUNT_LOCK_THRESHOLD
            lock_seconds = min(
                settings.LOGIN_ACCOUNT_LOCK_BASE_SECONDS * (2**excess),
                settings.LOGIN_ACCOUNT_LOCK_MAX_SECONDS,
            )
            state.lock_expiry = now + lock_seconds

    def reset(self, username: str) -> None:
        self._state.pop(_normalize(username), None)


in_memory_account_login_guard = _InMemoryAccountLoginGuard()


class AccountLoginGuard:
    def __init__(self) -> None:
        self._script_sha: str | None = None
        self._fallback = in_memory_account_login_guard

    def _keys(self, username: str) -> tuple[str, str]:
        normalized = _normalize(username)
        prefix = f"{settings.REDIS_KEY_PREFIX}:loginguard"
        return f"{prefix}:fail:{normalized}", f"{prefix}:lock:{normalized}"

    async def is_locked(self, username: str) -> int | None:
        """Returns remaining lock seconds, or None if not currently locked."""
        _, lock_key = self._keys(username)
        try:
            client = get_redis()
            ttl = await client.ttl(lock_key)
        except (RuntimeError, RedisError) as exc:
            logger.warning("Login guard Redis unavailable for is_locked (%s) - using fallback", exc)
            return self._fallback.is_locked(username)
        return ttl if ttl > 0 else None

    async def record_failure(self, username: str) -> None:
        fail_key, lock_key = self._keys(username)
        try:
            client = get_redis()
            if self._script_sha is None:
                self._script_sha = await client.script_load(_RECORD_FAILURE_SCRIPT)
            await client.evalsha(
                self._script_sha,
                2,
                fail_key,
                lock_key,
                str(settings.LOGIN_ACCOUNT_FAIL_WINDOW_SECONDS),
                str(settings.LOGIN_ACCOUNT_LOCK_THRESHOLD),
                str(settings.LOGIN_ACCOUNT_LOCK_BASE_SECONDS),
                str(settings.LOGIN_ACCOUNT_LOCK_MAX_SECONDS),
            )
        except (RuntimeError, RedisError) as exc:
            logger.warning(
                "Login guard Redis unavailable for record_failure (%s) - using fallback", exc
            )
            self._fallback.record_failure(username)

    async def reset(self, username: str) -> None:
        fail_key, lock_key = self._keys(username)
        try:
            client = get_redis()
            await client.delete(fail_key, lock_key)
        except (RuntimeError, RedisError) as exc:
            logger.warning("Login guard Redis unavailable for reset (%s) - using fallback", exc)
        self._fallback.reset(username)
