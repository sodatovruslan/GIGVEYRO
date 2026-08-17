from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_account, get_db
from app.core.config import settings
from app.models.account import Account
from app.repositories.telegram import TelegramLinkRepository
from app.schemas.notification import TelegramLinkCodeRead, TelegramWebhookPayload
from app.services.telegram import TelegramService

router = APIRouter(prefix="/telegram", tags=["telegram"])


@router.post("/link-code", response_model=TelegramLinkCodeRead)
async def create_telegram_link_code(
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
):
    repo = TelegramLinkRepository(session)
    service = TelegramService(repo)
    raw_code, link = await service.generate_link_code(account.id)
    return TelegramLinkCodeRead(
        verification_code=raw_code,
        expires_at=link.verification_expires_at,
    )


@router.post("/webhook")
async def telegram_webhook(
    payload: TelegramWebhookPayload,
    session: AsyncSession = Depends(get_db),
):
    # DEV-only / Mock mock-endpoint protection
    if getattr(settings, "APP_ENV", "development").lower() == "production":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Telegram webhook endpoint is disabled in production.",
        )

    if not payload.message:
        return {"status": "ok", "processed": False}

    msg = payload.message
    chat = msg.get("chat", {})
    from_user = msg.get("from", {})
    text = msg.get("text", "")

    chat_id = chat.get("id")
    user_id = from_user.get("id")

    if not chat_id or not user_id or not text:
        return {"status": "ok", "processed": False}

    repo = TelegramLinkRepository(session)
    service = TelegramService(repo)
    response_text = await service.process_telegram_command(
        telegram_user_id=user_id, chat_id=chat_id, text=text
    )

    return {"status": "ok", "processed": True, "reply": response_text}
