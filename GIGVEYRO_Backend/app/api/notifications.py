import uuid
from typing import Sequence
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_account, get_db
from app.enums.notification import NotificationType
from app.models.account import Account
from app.repositories.notification import NotificationRepository
from app.schemas.notification import (
    NotificationPreferenceRead,
    NotificationPreferenceUpdate,
    NotificationRead,
    UnreadCountRead,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("/preferences", response_model=NotificationPreferenceRead)
async def get_notification_preferences(
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
):
    repo = NotificationRepository(session)
    return await repo.get_or_create_preference(account.id)


@router.patch("/preferences", response_model=NotificationPreferenceRead)
async def update_notification_preferences(
    payload: NotificationPreferenceUpdate,
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
):
    repo = NotificationRepository(session)
    pref = await repo.get_or_create_preference(account.id)
    return await repo.update_preference(pref, payload.model_dump(exclude_unset=True))


@router.get("", response_model=list[NotificationRead])
async def list_notifications(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    unread_only: bool = Query(False),
    type: NotificationType | None = Query(None),
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
):
    repo = NotificationRepository(session)
    return await repo.list_for_account(
        account_id=account.id,
        limit=limit,
        offset=offset,
        unread_only=unread_only,
        type_=type,
    )


@router.get("/unread-count", response_model=UnreadCountRead)
async def get_unread_count(
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
):
    repo = NotificationRepository(session)
    count = await repo.get_unread_count(account.id)
    return UnreadCountRead(unread_count=count)


@router.get("/{notification_id}", response_model=NotificationRead)
async def get_notification_by_id(
    notification_id: uuid.UUID,
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
):
    repo = NotificationRepository(session)
    notif = await repo.get_by_id_and_account(notification_id, account.id)
    if not notif:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    return notif


@router.post("/read-all", status_code=status.HTTP_200_OK)
async def mark_all_notifications_as_read(
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
):
    repo = NotificationRepository(session)
    updated_count = await repo.mark_all_as_read(account.id)
    return {"updated_count": updated_count}


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
