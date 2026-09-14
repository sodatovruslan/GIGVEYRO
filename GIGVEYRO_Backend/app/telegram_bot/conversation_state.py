"""Ephemeral per-Telegram-user UI state for multi-step menu flows (e.g.
"enter withdrawal amount" -> "enter destination" -> "confirm"). This is
navigation state only - it never holds a balance, a computed amount, or
any value the backend would trust. Every mutating action re-reads the
authoritative state from the database at execution time.

Same fail-mode philosophy as RedisRateLimiter: Redis first, in-memory
per-process fallback if Redis is unavailable (matches how the interactive
Telegram command service is exercised in tests, which never call
init_redis())."""

from __future__ import annotations

import json
import time
from typing import Any

from redis.exceptions import RedisError

from app.core.config import settings
from app.infra.redis_client import get_redis

TTL_SECONDS = 600


class _InMemoryConversationStore:
    def __init__(self) -> None:
        self._data: dict[int, tuple[float, dict[str, Any]]] = {}

    def get(self, telegram_user_id: int) -> dict[str, Any] | None:
        entry = self._data.get(telegram_user_id)
        if entry is None:
            return None
        expires_at, payload = entry
        if expires_at < time.time():
            self._data.pop(telegram_user_id, None)
            return None
        return payload

    def set(self, telegram_user_id: int, payload: dict[str, Any]) -> None:
        self._data[telegram_user_id] = (time.time() + TTL_SECONDS, payload)

    def clear(self, telegram_user_id: int) -> None:
        self._data.pop(telegram_user_id, None)

    def clear_all(self) -> None:
        self._data.clear()


in_memory_conversation_store = _InMemoryConversationStore()


def _key(telegram_user_id: int) -> str:
    return f"{settings.REDIS_KEY_PREFIX}:tgstate:{telegram_user_id}"


async def get_pending(telegram_user_id: int) -> dict[str, Any] | None:
    try:
        raw = await get_redis().get(_key(telegram_user_id))
    except (RuntimeError, RedisError):
        return in_memory_conversation_store.get(telegram_user_id)
    return json.loads(raw) if raw else None


async def set_pending(telegram_user_id: int, payload: dict[str, Any]) -> None:
    try:
        await get_redis().set(_key(telegram_user_id), json.dumps(payload), ex=TTL_SECONDS)
    except (RuntimeError, RedisError):
        in_memory_conversation_store.set(telegram_user_id, payload)


async def clear_pending(telegram_user_id: int) -> None:
    try:
        await get_redis().delete(_key(telegram_user_id))
    except (RuntimeError, RedisError):
        pass
    in_memory_conversation_store.clear(telegram_user_id)
