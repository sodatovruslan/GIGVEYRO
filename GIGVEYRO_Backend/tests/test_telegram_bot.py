import asyncio
import uuid

import pytest
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.methods import SendMessage
from sqlalchemy import delete, select

from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.db.session import AsyncSessionLocal
from app.enums.account import UserRole
from app.models.account import Account
from app.models.audit import AuditLog
from app.models.telegram import TelegramAccountLink, TelegramLinkToken
from app.repositories.telegram import TelegramLinkRepository
from app.services.telegram import TelegramLinkError, TelegramService
from app.services.telegram_provider import (
    AiogramTelegramProvider,
    MockTelegramProvider,
    TelegramDeliveryError,
    telegram_diagnostics,
)
from app.telegram_bot.commands import TelegramCommandService


def _headers(account) -> dict[str, str]:
    token = create_access_token(account.id, account.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _allow_commands(monkeypatch):
    async def allowed(*args, **kwargs):  # noqa: ANN002, ANN003
        return False

    monkeypatch.setattr(
        "app.telegram_bot.commands.RedisRateLimiter.is_rate_limited", allowed
    )


@pytest.mark.asyncio
async def test_link_identity_conflict_block_and_relink(db_session, make_account):
    first = await make_account()
    second = await make_account()
    first_service = TelegramService(TelegramLinkRepository(db_session))
    first_token, _ = await first_service.generate_link_token(first)
    result = await first_service.consume_link_token(
        raw_token=first_token,
        telegram_user_id=456,
        chat_id=456,
        username="metadata-only",
        first_name=None,
        telegram_language="ru",
    )
    assert result.connection.telegram_user_id == 456

    second_token, _ = await first_service.generate_link_token(second)
    with pytest.raises(TelegramLinkError):
        await first_service.consume_link_token(
            raw_token=second_token,
            telegram_user_id=456,
            chat_id=456,
            username="renamed",
            first_name=None,
            telegram_language="ru",
        )

    await first_service.disconnect(result.connection, first)
    relink = await first_service.consume_link_token(
        raw_token=second_token,
        telegram_user_id=456,
        chat_id=456,
        username="renamed",
        first_name=None,
        telegram_language="en",
    )
    assert relink.connection.account_id == second.id


@pytest.mark.asyncio
async def test_concurrent_double_consume_has_exactly_one_winner():
    account_id = uuid.uuid4()
    async with AsyncSessionLocal() as session:
        account = Account(
            id=account_id,
            username=f"telegram_race_{uuid.uuid4().hex[:8]}",
            password_hash=hash_password("TelegramRacePassword123"),
            role=UserRole.USER,
            full_name="Telegram Race",
            is_active=True,
        )
        session.add(account)
        await session.flush()
        raw_token, _ = await TelegramService(
            TelegramLinkRepository(session)
        ).generate_link_token(account)
        await session.commit()

    async def consume(user_id: int) -> bool:
        async with AsyncSessionLocal() as session:
            try:
                await TelegramService(TelegramLinkRepository(session)).consume_link_token(
                    raw_token=raw_token,
                    telegram_user_id=user_id,
                    chat_id=user_id,
                    username=None,
                    first_name=None,
                    telegram_language="en",
                )
                await session.commit()
                return True
            except TelegramLinkError:
                await session.rollback()
                return False

    try:
        assert sum(await asyncio.gather(consume(9001), consume(9002))) == 1
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(AuditLog).where(AuditLog.actor_account_id == account_id)
            )
            await session.execute(delete(Account).where(Account.id == account_id))
            await session.commit()


@pytest.mark.asyncio
async def test_commands_are_read_only_role_scoped_and_require_active_account(
    db_session, make_account, make_wallet, monkeypatch
):
    await _allow_commands(monkeypatch)
    account = await make_account()
    await make_wallet(account)
    commands = TelegramCommandService(db_session)
    token, _ = await commands.telegram.generate_link_token(account)
    assert "connected" in (
        await commands.handle(
            telegram_user_id=88,
            chat_id=99,
            text_value=f"/start {token}",
            telegram_language="en",
        )
    ).lower()
    assert "0.00 USDT" in await commands.handle(
        telegram_user_id=88, chat_id=99, text_value="/balance"
    )
    assert "unknown" in (
        await commands.handle(
            telegram_user_id=88,
            chat_id=99,
            text_value="/withdraw 100",
        )
    ).lower()
    assert "not connected" in (
        await commands.handle(
            telegram_user_id=88,
            chat_id=100,
            text_value="/status",
            telegram_language="en",
        )
    ).lower()
    account.is_active = False
    await db_session.flush()
    assert "temporarily unavailable" in (
        await commands.handle(
            telegram_user_id=88, chat_id=99, text_value="/status"
        )
    ).lower()


@pytest.mark.asyncio
async def test_owner_and_merchant_command_boundaries(
    db_session, make_account, make_merchant_wallet, monkeypatch
):
    await _allow_commands(monkeypatch)
    owner = await make_account(role=UserRole.OWNER)
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant)
    commands = TelegramCommandService(db_session)

    owner_token, _ = await commands.telegram.generate_link_token(owner)
    await commands.handle(
        telegram_user_id=501,
        chat_id=501,
        text_value=f"/start {owner_token}",
        telegram_language="en",
    )
    assert "risk" in (
        await commands.handle(telegram_user_id=501, chat_id=501, text_value="/status")
    ).lower()
    assert "unknown" in (
        await commands.handle(telegram_user_id=501, chat_id=501, text_value="/balance")
    ).lower()

    merchant_token, _ = await commands.telegram.generate_link_token(merchant)
    await commands.handle(
        telegram_user_id=502,
        chat_id=502,
        text_value=f"/start {merchant_token}",
        telegram_language="en",
    )
    assert "0.00 USDT" in await commands.handle(
        telegram_user_id=502, chat_id=502, text_value="/balance"
    )
    assert "unknown" in (
        await commands.handle(telegram_user_id=502, chat_id=502, text_value="/risk")
    ).lower()


@pytest.mark.asyncio
async def test_authenticated_connection_api_and_webhook_secret(
    client, db_session, make_account, monkeypatch
):
    account = await make_account()
    monkeypatch.setattr(settings, "TELEGRAM_BOT_ENABLED", True)
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "gigveyro_test_bot")
    response = await client.post("/telegram/link-token", headers=_headers(account))
    assert response.status_code == 200
    body = response.json()
    assert body["deep_link"].startswith("https://t.me/gigveyro_test_bot?start=")
    raw_token = body["deep_link"].split("start=", 1)[1]
    stored = (await db_session.execute(select(TelegramLinkToken))).scalar_one()
    assert stored.token_hash != raw_token

    assert (await client.get("/telegram/connection", headers=_headers(account))).json() == {
        "connected": False,
        "masked_username": None,
        "linked_at": None,
        "language": "ru",
        "delivery_enabled": False,
        "unhealthy_reason": None,
    }
    invalid = await client.post(
        "/telegram/webhook",
        json={"update_id": 1},
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
    )
    assert invalid.status_code == 404

    await _allow_commands(monkeypatch)
    monkeypatch.setattr(settings, "TELEGRAM_BOT_MODE", "webhook")
    secret_type = type(settings.TELEGRAM_WEBHOOK_SECRET)
    monkeypatch.setattr(
        settings, "TELEGRAM_WEBHOOK_SECRET", secret_type("safe-test-secret")
    )
    provider = MockTelegramProvider()
    monkeypatch.setattr("app.api.telegram.get_telegram_provider", lambda: provider)
    valid = await client.post(
        "/telegram/webhook",
        json={
            "update_id": 2,
            "message": {
                "text": f"/start {raw_token}",
                "chat": {"id": 777, "type": "private"},
                "from": {"id": 777, "language_code": "tg", "username": "ignored"},
            },
        },
        headers={"X-Telegram-Bot-Api-Secret-Token": "safe-test-secret"},
    )
    assert valid.status_code == 200
    assert len(provider.sent_messages) == 1
    connection = (await db_session.execute(select(TelegramAccountLink))).scalar_one()
    assert connection.telegram_user_id == 777
    assert connection.language == "tg"

    patch = await client.patch(
        "/telegram/connection",
        json={"language": "en", "delivery_enabled": False},
        headers=_headers(account),
    )
    assert patch.status_code == 200
    assert patch.json()["language"] == "en"
    assert patch.json()["delivery_enabled"] is False
    assert (
        await client.delete("/telegram/connection", headers=_headers(account))
    ).status_code == 204

    actions = set((await db_session.execute(select(AuditLog.action))).scalars())
    assert {
        "telegram.link_token_created",
        "telegram.connected",
        "telegram.language_changed",
        "telegram.delivery_disabled",
        "telegram.disconnected",
    } <= actions


def test_telegram_diagnostics_never_expose_secret(monkeypatch):
    secret_type = type(settings.TELEGRAM_BOT_TOKEN)
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", secret_type("123:do-not-expose"))
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "safe_name")
    diagnostics = telegram_diagnostics()
    assert diagnostics["configured"] is True
    assert "token" not in diagnostics
    assert "123:do-not-expose" not in repr(diagnostics)


class _FailingBot:
    def __init__(self, error: Exception):
        self.error = error

    async def send_message(self, **kwargs):  # noqa: ANN003, ANN201
        raise self.error


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exception", "category", "retryable", "retry_after"),
    [
        (
            TelegramNetworkError(SendMessage(chat_id=1, text="x"), "timeout"),
            "temporary_unavailable",
            True,
            None,
        ),
        (
            TelegramServerError(SendMessage(chat_id=1, text="x"), "server"),
            "temporary_unavailable",
            True,
            None,
        ),
        (
            TelegramRetryAfter(SendMessage(chat_id=1, text="x"), "retry", 7),
            "rate_limited",
            True,
            7,
        ),
        (
            TelegramForbiddenError(SendMessage(chat_id=1, text="x"), "blocked"),
            "blocked",
            False,
            None,
        ),
        (
            TelegramBadRequest(SendMessage(chat_id=1, text="x"), "chat not found"),
            "chat_not_found",
            False,
            None,
        ),
    ],
)
async def test_provider_classifies_delivery_failures(
    exception, category, retryable, retry_after
):  # noqa: ANN001
    provider = AiogramTelegramProvider(bot=_FailingBot(exception))
    with pytest.raises(TelegramDeliveryError) as captured:
        await provider.send_message(1, "safe text")
    assert captured.value.category == category
    assert captured.value.retryable is retryable
    assert captured.value.retry_after == retry_after
