import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_account, get_db, require_roles
from app.enums.account import UserRole
from app.enums.notification import NotificationChannel, NotificationStatus, NotificationType
from app.models.account import Account
from app.repositories.notification import NotificationRepository
from app.schemas.notification import (
    NotificationDeliveryRead,
    NotificationPreferenceRead,
    NotificationPreferenceUpdate,
    NotificationRead,
    UnreadCountRead,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])
require_owner = require_roles(UserRole.OWNER)


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


# --- OWNER MONITORING ENDPOINTS ---


@router.get("/owner/deliveries", response_model=list[NotificationDeliveryRead])
async def list_deliveries_for_owner(
    status: NotificationStatus | None = Query(None),
    channel: NotificationChannel | None = Query(None),
    account_id: uuid.UUID | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _: Account = Depends(require_owner),
    session: AsyncSession = Depends(get_db),
):
    repo = NotificationRepository(session)
    return await repo.list_deliveries_for_owner(
        status=status,
        channel=channel,
        account_id=account_id,
        limit=limit,
        offset=offset,
    )


@router.post("/owner/deliveries/{delivery_id}/retry", response_model=NotificationDeliveryRead)
async def retry_failed_delivery_for_owner(
    delivery_id: uuid.UUID,
    _: Account = Depends(require_owner),
    session: AsyncSession = Depends(get_db),
):
    repo = NotificationRepository(session)
    delivery = await repo.get_delivery_by_id(delivery_id)
    if not delivery:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Delivery record not found"
        )
    if delivery.status != NotificationStatus.FAILED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only FAILED deliveries can be retried",
        )

    delivery.status = NotificationStatus.PENDING
    delivery.last_error = None
    await session.flush()
    return delivery
