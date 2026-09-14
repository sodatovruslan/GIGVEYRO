from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from typing import NamedTuple

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
    TelegramUnauthorizedError,
)
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.token import TokenValidationError

from app.core.config import settings
from app.infra.metrics import record_telegram_delivery

logger = logging.getLogger(__name__)


class TelegramMessage(NamedTuple):
    chat_id: int
    text: str
    web_url: str | None = None
    button_text: str | None = None
    reply_markup: InlineKeyboardMarkup | None = None


@dataclass(frozen=True)
class TelegramDeliveryError(Exception):
    category: str
    retryable: bool
    retry_after: int | None = None

    def __str__(self) -> str:
        return self.category


class TelegramProvider(ABC):
    @abstractmethod
    async def send_message(
        self,
        chat_id: int,
        text: str,
        web_url: str | None = None,
        button_text: str | None = None,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> bool:
        """Send a sanitized message. Implementations must never log its content.

        `reply_markup`, when given, takes precedence over `web_url`/`button_text`
        (which remain for the single-deep-link-button push-notification case)."""

    async def edit_message(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> bool:
        """Edit an existing message in place (interactive menu navigation)."""
        raise NotImplementedError

    async def answer_callback(self, callback_query_id: str, text: str | None = None) -> None:
        """Acknowledge a callback_query so Telegram stops showing the spinner."""
        raise NotImplementedError

    async def close(self) -> None:
        return None


class AiogramTelegramProvider(TelegramProvider):
    def __init__(self, bot: Bot | None = None):
        self._bot = bot
        self.last_success_at: datetime | None = None
        self.last_error_category: str | None = None

    def _get_bot(self) -> Bot:
        if self._bot is None:
            self._bot = Bot(
                token=settings.TELEGRAM_BOT_TOKEN.get_secret_value(),
                session=AiohttpSession(timeout=settings.TELEGRAM_API_TIMEOUT_SECONDS),
            )
        return self._bot

    async def send_message(
        self,
        chat_id: int,
        text: str,
        web_url: str | None = None,
        button_text: str | None = None,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> bool:
        started = monotonic()
        if reply_markup is None and web_url:
            reply_markup = InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text=button_text or "GigaPay", url=web_url)]]
            )
        try:
            await self._get_bot().send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                protect_content=True,
            )
            self.last_success_at = datetime.now(UTC)
            self.last_error_category = None
            record_telegram_delivery("success", monotonic() - started)
            return True
        except TelegramRetryAfter as exc:
            self.last_error_category = "rate_limited"
            record_telegram_delivery("retry", monotonic() - started)
            raise TelegramDeliveryError(
                "rate_limited", retryable=True, retry_after=int(exc.retry_after)
            ) from exc
        except TelegramForbiddenError as exc:
            self.last_error_category = "blocked"
            record_telegram_delivery("blocked", monotonic() - started)
            raise TelegramDeliveryError("blocked", retryable=False) from exc
        except TelegramBadRequest as exc:
            message = str(exc).lower()
            category = next(
                (
                    safe_category
                    for marker, safe_category in (
                        ("chat not found", "chat_not_found"),
                        ("button_url_invalid", "button_url_invalid"),
                        ("button_type_invalid", "button_type_invalid"),
                        ("message text is empty", "message_empty"),
                        ("message is too long", "message_too_long"),
                        ("not enough rights", "insufficient_rights"),
                        ("can't parse entities", "invalid_entities"),
                        ("message thread not found", "thread_not_found"),
                    )
                    if marker in message
                ),
                "bad_request",
            )
            safe_reason = exc.message.replace(
                settings.TELEGRAM_BOT_TOKEN.get_secret_value(), "<redacted>"
            )
            safe_reason = re.sub(r"https?://\S+", "<url>", safe_reason)
            safe_reason = re.sub(r"\d+", "<number>", safe_reason)[:180]
            logger.warning(
                "telegram.delivery.bad_request reason=%s",
                safe_reason,
            )
            self.last_error_category = category
            record_telegram_delivery("failed", monotonic() - started)
            raise TelegramDeliveryError(category, retryable=False) from exc
        except TelegramUnauthorizedError as exc:
            self.last_error_category = "invalid_token"
            record_telegram_delivery("failed", monotonic() - started)
            raise TelegramDeliveryError("invalid_token", retryable=False) from exc
        except TokenValidationError as exc:
            self.last_error_category = "invalid_config"
            record_telegram_delivery("failed", monotonic() - started)
            raise TelegramDeliveryError("invalid_config", retryable=False) from exc
        except (TelegramNetworkError, TelegramServerError) as exc:
            self.last_error_category = "temporary_unavailable"
            record_telegram_delivery("retry", monotonic() - started)
            raise TelegramDeliveryError("temporary_unavailable", retryable=True) from exc

    async def edit_message(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> bool:
        started = monotonic()
        try:
            await self._get_bot().edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup,
            )
            self.last_success_at = datetime.now(UTC)
            record_telegram_delivery("success", monotonic() - started)
            return True
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                return True
            record_telegram_delivery("failed", monotonic() - started)
            raise TelegramDeliveryError("bad_request", retryable=False) from exc
        except TelegramRetryAfter as exc:
            record_telegram_delivery("retry", monotonic() - started)
            raise TelegramDeliveryError(
                "rate_limited", retryable=True, retry_after=int(exc.retry_after)
            ) from exc
        except TelegramForbiddenError as exc:
            record_telegram_delivery("blocked", monotonic() - started)
            raise TelegramDeliveryError("blocked", retryable=False) from exc
        except (TelegramNetworkError, TelegramServerError) as exc:
            record_telegram_delivery("retry", monotonic() - started)
            raise TelegramDeliveryError("temporary_unavailable", retryable=True) from exc

    async def answer_callback(self, callback_query_id: str, text: str | None = None) -> None:
        try:
            await self._get_bot().answer_callback_query(
                callback_query_id=callback_query_id, text=text
            )
        except (TelegramBadRequest, TelegramNetworkError, TelegramServerError) as exc:
            logger.warning("telegram.callback.answer_failed category=%s", type(exc).__name__)

    async def get_me(self):  # noqa: ANN201
        try:
            result = await self._get_bot().get_me()
            self.last_success_at = datetime.now(UTC)
            self.last_error_category = None
            return result
        except Exception as exc:
            self.last_error_category = "unavailable"
            raise TelegramDeliveryError("unavailable", retryable=True) from exc

    async def close(self) -> None:
        if self._bot is not None:
            await self._bot.session.close()
            self._bot = None


class MockTelegramProvider(TelegramProvider):
    def __init__(
        self,
        should_fail: bool = False,
        error: TelegramDeliveryError | None = None,
    ):
        self.should_fail = should_fail
        self.error = error
        self.sent_messages: list[TelegramMessage] = []
        self.edited_messages: list[TelegramMessage] = []
        self.answered_callbacks: list[tuple[str, str | None]] = []

    async def send_message(
        self,
        chat_id: int,
        text: str,
        web_url: str | None = None,
        button_text: str | None = None,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> bool:
        if self.error:
            raise self.error
        if self.should_fail:
            raise TelegramDeliveryError("temporary_unavailable", retryable=True)
        self.sent_messages.append(
            TelegramMessage(
                chat_id=chat_id,
                text=text,
                web_url=web_url,
                button_text=button_text,
                reply_markup=reply_markup,
            )
        )
        return True

    async def edit_message(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> bool:
        if self.error:
            raise self.error
        if self.should_fail:
            raise TelegramDeliveryError("temporary_unavailable", retryable=True)
        self.edited_messages.append(
            TelegramMessage(chat_id=chat_id, text=text, reply_markup=reply_markup)
        )
        return True

    async def answer_callback(self, callback_query_id: str, text: str | None = None) -> None:
        self.answered_callbacks.append((callback_query_id, text))

    def clear(self) -> None:
        self.sent_messages.clear()
        self.edited_messages.clear()
        self.answered_callbacks.clear()


_provider: AiogramTelegramProvider | None = None


def get_telegram_provider() -> AiogramTelegramProvider:
    global _provider  # noqa: PLW0603
    if _provider is None:
        _provider = AiogramTelegramProvider()
    return _provider


async def close_telegram_provider() -> None:
    global _provider  # noqa: PLW0603
    if _provider is not None:
        await _provider.close()
        _provider = None


def telegram_diagnostics() -> dict[str, object]:
    return {
        "configured": bool(
            settings.TELEGRAM_BOT_TOKEN.get_secret_value() and settings.TELEGRAM_BOT_USERNAME
        ),
        "enabled": settings.TELEGRAM_BOT_ENABLED,
        "mode": settings.TELEGRAM_BOT_MODE,
        "delivery_enabled": settings.TELEGRAM_DELIVERY_ENABLED,
        "last_success_at": _provider.last_success_at.isoformat()
        if _provider and _provider.last_success_at
        else None,
        "last_error_category": _provider.last_error_category if _provider else None,
    }
