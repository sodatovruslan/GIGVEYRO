import uuid
from typing import Sequence
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_account, get_db
from app.models.account import Account
from app.repositories.notification import NotificationRepository
from app.schemas.notification import NotificationRead

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationRead])
async def list_notifications(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    unread_only: bool = Query(False),
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
):
    repo = NotificationRepository(session)
    return await repo.list_for_account(
        account_id=account.id,
        limit=limit,
        offset=offset,
        unread_only=unread_only,
    )


@router.post("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_notification_as_read(
    notification_id: uuid.UUID,
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
):
    repo = NotificationRepository(session)
    updated = await repo.mark_as_read(notification_id=notification_id, account_id=account.id)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )
