from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.rate_limit import enforce_rate_limit
from app.db.session import get_db
from app.repositories.access_request import AccessRequestRepository
from app.repositories.account import AccountRepository
from app.repositories.notification import NotificationRepository
from app.repositories.telegram import TelegramLinkRepository
from app.schemas.access_request import AccessRequestAck, AccessRequestCreate
from app.services.access_request import AccessRequestService
from app.services.notification import NotificationService
from app.services.telegram_provider import MockTelegramProvider

router = APIRouter(prefix="/access-requests", tags=["Public Access Requests"])


def _service(db: AsyncSession = Depends(get_db)) -> AccessRequestService:
    return AccessRequestService(
        AccessRequestRepository(db),
        AccountRepository(db),
        NotificationService(
            NotificationRepository(db), TelegramLinkRepository(db), MockTelegramProvider()
        ),
    )


@router.post("", response_model=AccessRequestAck)
async def create_access_request(
    payload: AccessRequestCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    service: AccessRequestService = Depends(_service),
) -> AccessRequestAck:
    """Unauthenticated - a visitor without an account asks the Owner for
    one. Never creates an Account; public registration stays disabled."""
    client_ip = request.client.host if request.client else "127.0.0.1"
    await enforce_rate_limit(
        f"access_request:{client_ip}",
        settings.ACCESS_REQUEST_RATE_LIMIT_REQUESTS,
        settings.ACCESS_REQUEST_RATE_LIMIT_WINDOW_SECONDS,
    )
    await service.submit(
        full_name=payload.full_name,
        contact=payload.contact,
        note=payload.note,
        client_ip=client_ip,
    )
    await db.commit()
    return AccessRequestAck()
