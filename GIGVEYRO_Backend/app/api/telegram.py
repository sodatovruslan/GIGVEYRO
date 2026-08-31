import logging
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_account, get_db
from app.core.config import settings
from app.models.account import Account
from app.repositories.telegram import TelegramLinkRepository
from app.schemas.notification import (
    TelegramConnectionRead,
    TelegramConnectionUpdate,
    TelegramLinkTokenRead,
    TelegramWebhookPayload,
)
from app.services.telegram import TelegramService
from app.services.telegram_provider import TelegramDeliveryError, get_telegram_provider
from app.telegram_bot.commands import TelegramCommandService

router = APIRouter(prefix="/telegram", tags=["telegram"])
logger = logging.getLogger(__name__)


def _masked_username(username: str | None) -> str | None:
    if not username:
        return None
    return f"@{username[:1]}{'*' * min(6, max(2, len(username) - 1))}"


def _connection_read(connection) -> TelegramConnectionRead:  # noqa: ANN001
    if connection is None or not connection.is_linked:
        return TelegramConnectionRead(connected=False)
    return TelegramConnectionRead(
        connected=True,
        masked_username=_masked_username(connection.telegram_username),
        linked_at=connection.linked_at,
        language=connection.language,
        delivery_enabled=connection.delivery_enabled,
        unhealthy_reason=connection.last_error_category,
    )


@router.get("/connection", response_model=TelegramConnectionRead)
async def get_telegram_connection(
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
):
    return _connection_read(await TelegramLinkRepository(session).get_by_account_id(account.id))


@router.post("/link-token", response_model=TelegramLinkTokenRead)
async def create_telegram_link_token(
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
):
    if not settings.TELEGRAM_BOT_ENABLED or not settings.TELEGRAM_BOT_USERNAME:
        raise HTTPException(status_code=503, detail="Telegram bot is not configured")
    raw_token, expires_at = await TelegramService(
        TelegramLinkRepository(session)
    ).generate_link_token(account)
    username = settings.TELEGRAM_BOT_USERNAME.lstrip("@")
    return TelegramLinkTokenRead(
        deep_link=f"https://t.me/{username}?start={raw_token}",
        expires_at=expires_at,
        bot_username=username,
    )


@router.patch("/connection", response_model=TelegramConnectionRead)
async def update_telegram_connection(
    payload: TelegramConnectionUpdate,
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
):
    repo = TelegramLinkRepository(session)
    connection = await repo.get_by_account_id(account.id, for_update=True)
    if connection is None or not connection.is_linked:
        raise HTTPException(status_code=404, detail="Telegram connection not found")
    service = TelegramService(repo)
    if payload.language is not None:
        await service.change_language(connection, account, payload.language)
    if payload.delivery_enabled is not None:
        await service.change_delivery(connection, account, payload.delivery_enabled)
    return _connection_read(connection)


@router.delete("/connection", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_telegram(
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
):
    repo = TelegramLinkRepository(session)
    connection = await repo.get_by_account_id(account.id, for_update=True)
    if connection is not None and connection.is_linked:
        await TelegramService(repo).disconnect(connection, account)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/webhook", include_in_schema=False)
async def telegram_webhook(
    payload: TelegramWebhookPayload,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
    session: AsyncSession = Depends(get_db),
):
    expected = settings.TELEGRAM_WEBHOOK_SECRET.get_secret_value()
    if (
        not settings.TELEGRAM_BOT_ENABLED
        or settings.TELEGRAM_BOT_MODE != "webhook"
        or not expected
        or not x_telegram_bot_api_secret_token
        or not secrets.compare_digest(expected, x_telegram_bot_api_secret_token)
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if not payload.message:
        return {"ok": True}
    message = payload.message
    chat = message.get("chat") or {}
    sender = message.get("from") or {}
    if chat.get("type") != "private" or not isinstance(message.get("text"), str):
        return {"ok": True}
    if not isinstance(chat.get("id"), int) or not isinstance(sender.get("id"), int):
        return {"ok": True}
    reply = await TelegramCommandService(session).handle(
        telegram_user_id=sender["id"],
        chat_id=chat["id"],
        text_value=message["text"],
        username=sender.get("username"),
        first_name=sender.get("first_name"),
        telegram_language=sender.get("language_code"),
    )
    # Persist linking/settings independently of Telegram's reply availability.
    await session.commit()
    try:
        await get_telegram_provider().send_message(chat["id"], reply)
    except TelegramDeliveryError as exc:
        logger.warning(
            "telegram_webhook_reply_failed", extra={"error_category": exc.category}
        )
    return {"ok": True}
