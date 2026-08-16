import uuid
from typing import Sequence
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums.notification import NotificationStatus
from app.models.notification import Notification, NotificationOutbox


class NotificationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_notification(self, notification: Notification) -> Notification:
        self.session.add(notification)
        await self.session.flush()
        return notification

    async def get_by_dedupe_hash(self, dedupe_hash: str) -> Notification | None:
        stmt = select(Notification).where(Notification.dedupe_hash == dedupe_hash)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def list_for_account(
        self,
        account_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
        unread_only: bool = False,
    ) -> Sequence[Notification]:
        stmt = select(Notification).where(Notification.account_id == account_id)
        if unread_only:
            stmt = stmt.where(Notification.is_read.is_(False))
        stmt = stmt.order_by(Notification.created_at.desc()).limit(limit).offset(offset)
        res = await self.session.execute(stmt)
        return res.scalars().all()

    async def mark_as_read(self, notification_id: uuid.UUID, account_id: uuid.UUID) -> bool:
        stmt = (
            update(Notification)
            .where(
                Notification.id == notification_id,
                Notification.account_id == account_id,
            )
            .values(is_read=True)
        )
        res = await self.session.execute(stmt)
        return res.rowcount > 0

    async def create_outbox_entry(self, entry: NotificationOutbox) -> NotificationOutbox:
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def get_pending_outbox_entries(self, limit: int = 100) -> Sequence[NotificationOutbox]:
        stmt = (
            select(NotificationOutbox)
            .where(
                NotificationOutbox.status == NotificationStatus.PENDING,
                NotificationOutbox.attempts < NotificationOutbox.max_attempts,
            )
            .order_by(NotificationOutbox.created_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        res = await self.session.execute(stmt)
        return res.scalars().all()
