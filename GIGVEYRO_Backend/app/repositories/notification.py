import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.enums.notification import NotificationChannel, NotificationStatus, NotificationType
from app.models.notification import (
    Notification,
    NotificationDelivery,
    NotificationOutbox,
    NotificationPreference,
)


class NotificationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_or_create_preference(self, account_id: uuid.UUID) -> NotificationPreference:
        stmt = select(NotificationPreference).where(NotificationPreference.account_id == account_id)
        res = await self.session.execute(stmt)
        pref = res.scalar_one_or_none()
        if not pref:
            pref = NotificationPreference(account_id=account_id)
            self.session.add(pref)
            await self.session.flush()
        return pref

    async def update_preference(
        self, pref: NotificationPreference, updates: dict
    ) -> NotificationPreference:
        for field, value in updates.items():
            if value is not None and hasattr(pref, field):
                setattr(pref, field, value)
        await self.session.flush()
        return pref

    async def create_notification(self, notification: Notification) -> Notification:
        self.session.add(notification)
        await self.session.flush()
        return notification

    async def get_by_dedupe_hash(self, dedupe_hash: str) -> Notification | None:
        stmt = select(Notification).where(Notification.dedupe_hash == dedupe_hash)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_by_id_and_account(
        self, notification_id: uuid.UUID, account_id: uuid.UUID
    ) -> Notification | None:
        stmt = (
            select(Notification)
            .options(selectinload(Notification.deliveries))
            .where(
                Notification.id == notification_id,
                Notification.account_id == account_id,
                Notification.in_app_visible.is_(True),
            )
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def list_for_account(
        self,
        account_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
        unread_only: bool = False,
        type_: NotificationType | None = None,
    ) -> Sequence[Notification]:
        stmt = (
            select(Notification)
            .options(selectinload(Notification.deliveries))
            .where(
                Notification.account_id == account_id,
                Notification.in_app_visible.is_(True),
            )
        )
        if unread_only:
            stmt = stmt.where(Notification.is_read.is_(False))
        if type_:
            stmt = stmt.where(Notification.type == type_)

        stmt = stmt.order_by(Notification.created_at.desc()).limit(limit).offset(offset)
        res = await self.session.execute(stmt)
        return res.scalars().all()

    async def get_unread_count(self, account_id: uuid.UUID) -> int:
        stmt = select(func.count(Notification.id)).where(
            Notification.account_id == account_id,
            Notification.in_app_visible.is_(True),
            Notification.is_read.is_(False),
        )
        res = await self.session.execute(stmt)
        return res.scalar_one() or 0

    async def mark_as_read(self, notification_id: uuid.UUID, account_id: uuid.UUID) -> bool:
        stmt = (
            update(Notification)
            .where(
                Notification.id == notification_id,
                Notification.account_id == account_id,
                Notification.in_app_visible.is_(True),
            )
            .values(is_read=True)
        )
        res = await self.session.execute(stmt)
        return res.rowcount > 0

    async def mark_all_as_read(self, account_id: uuid.UUID) -> int:
        stmt = (
            update(Notification)
            .where(
                Notification.account_id == account_id,
                Notification.in_app_visible.is_(True),
                Notification.is_read.is_(False),
            )
            .values(is_read=True)
        )
        res = await self.session.execute(stmt)
        return res.rowcount

    async def create_outbox_entry(self, entry: NotificationOutbox) -> NotificationOutbox:
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def flush_outbox_updates(self) -> None:
        await self.session.flush()

    async def get_pending_outbox_entries(self, limit: int = 100) -> Sequence[NotificationOutbox]:
        stmt = (
            select(NotificationOutbox)
            .where(
                NotificationOutbox.status == NotificationStatus.PENDING,
                NotificationOutbox.attempts < NotificationOutbox.max_attempts,
                (
                    NotificationOutbox.next_attempt_at.is_(None)
                    | (NotificationOutbox.next_attempt_at <= datetime.now(UTC))
                ),
            )
            .order_by(NotificationOutbox.created_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        res = await self.session.execute(stmt)
        return res.scalars().all()

    async def create_delivery(self, delivery: NotificationDelivery) -> NotificationDelivery:
        self.session.add(delivery)
        await self.session.flush()
        return delivery

    async def get_telegram_delivery(
        self, notification_id: uuid.UUID
    ) -> NotificationDelivery | None:
        result = await self.session.execute(
            select(NotificationDelivery).where(
                NotificationDelivery.notification_id == notification_id,
                NotificationDelivery.channel == NotificationChannel.TELEGRAM,
            )
        )
        return result.scalar_one_or_none()

    async def list_deliveries_for_owner(
        self,
        status: NotificationStatus | None = None,
        channel: NotificationChannel | None = None,
        account_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[NotificationDelivery]:
        stmt = select(NotificationDelivery).join(Notification)
        if status:
            stmt = stmt.where(NotificationDelivery.status == status)
        if channel:
            stmt = stmt.where(NotificationDelivery.channel == channel)
        if account_id:
            stmt = stmt.where(Notification.account_id == account_id)

        stmt = stmt.order_by(NotificationDelivery.created_at.desc()).limit(limit).offset(offset)
        res = await self.session.execute(stmt)
        return res.scalars().all()

    async def get_delivery_by_id(self, delivery_id: uuid.UUID) -> NotificationDelivery | None:
        stmt = select(NotificationDelivery).where(NotificationDelivery.id == delivery_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()
