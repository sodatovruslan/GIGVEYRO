import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

from app.enums.notification import NotificationChannel, NotificationStatus, NotificationType
from app.models.notification import Notification, NotificationDelivery, NotificationOutbox
from app.repositories.notification import NotificationRepository
from app.repositories.telegram import TelegramLinkRepository
from app.services.telegram_provider import TelegramProvider


class NotificationService:
    def __init__(
        self,
        notification_repo: NotificationRepository,
        telegram_repo: TelegramLinkRepository,
        telegram_provider: TelegramProvider,
    ):
        self.notification_repo = notification_repo
        self.telegram_repo = telegram_repo
        self.telegram_provider = telegram_provider

    @staticmethod
    def generate_dedupe_hash(
        account_id: uuid.UUID,
        type_: NotificationType,
        key: str,
    ) -> str:
        raw = f"{account_id}:{type_}:{key}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _is_type_enabled(self, pref, type_: NotificationType) -> bool:
        if type_ in (
            NotificationType.DEAL_CREATED,
            NotificationType.DEAL_ACCEPTED,
            NotificationType.DEAL_PAID,
            NotificationType.DEAL_COMPLETED,
            NotificationType.DEAL_CANCELLED,
        ):
            return pref.deal_notifications
        elif type_ == NotificationType.DEPOSIT_CONFIRMED:
            return pref.deposit_notifications
        elif type_ in (NotificationType.APPEAL_OPENED, NotificationType.APPEAL_RESOLVED):
            return pref.appeal_notifications
        elif type_ == NotificationType.WITHDRAWAL_STATUS_CHANGED:
            return pref.withdrawal_notifications
        return True

    async def emit_notification(
        self,
        account_id: uuid.UUID,
        type_: NotificationType,
        title: str,
        message: str,
        payload: dict[str, Any] | None = None,
        dedupe_key: str | None = None,
    ) -> Notification | None:
        pref = await self.notification_repo.get_or_create_preference(account_id)
        if not self._is_type_enabled(pref, type_):
            return None

        dedupe_hash = (
            self.generate_dedupe_hash(account_id, type_, dedupe_key) if dedupe_key else None
        )

        if dedupe_hash:
            existing = await self.notification_repo.get_by_dedupe_hash(dedupe_hash)
            if existing:
                return existing

        # Create In-App Notification if enabled
        notification = None
        if pref.in_app_enabled:
            notification = Notification(
                account_id=account_id,
                type=type_,
                title=title,
                message=message,
                payload=payload,
                dedupe_hash=dedupe_hash,
                is_read=False,
            )
            notification = await self.notification_repo.create_notification(notification)

            # Delivery record for IN_APP
            delivery = NotificationDelivery(
                notification_id=notification.id,
                channel=NotificationChannel.IN_APP,
                status=NotificationStatus.SENT,
                attempts=1,
                sent_at=datetime.now(UTC),
            )
            await self.notification_repo.create_delivery(delivery)

        # Enqueue Outbox entry for Telegram if enabled
        if pref.telegram_enabled:
            outbox = NotificationOutbox(
                account_id=account_id,
                type=type_,
                title=title,
                message=message,
                payload=payload,
                dedupe_hash=dedupe_hash,
                status=NotificationStatus.PENDING,
            )
            await self.notification_repo.create_outbox_entry(outbox)

        return notification

    async def process_outbox_batch(self, limit: int = 50) -> int:
        entries = await self.notification_repo.get_pending_outbox_entries(limit=limit)
        processed_count = 0

        for entry in entries:
            entry.attempts += 1
            try:
                tg_link = await self.telegram_repo.get_by_account_id(entry.account_id)
                sent_ok = False
                err_msg = None

                if tg_link and tg_link.is_linked and tg_link.chat_id:
                    try:
                        sent_ok = await self.telegram_provider.send_message(
                            tg_link.chat_id, f"<b>{entry.title}</b>\n{entry.message}"
                        )
                    except Exception as ex:
                        err_msg = str(ex)
                else:
                    err_msg = "User not linked to Telegram"

                if sent_ok:
                    entry.status = NotificationStatus.SENT
                    entry.processed_at = datetime.now(UTC)
                    processed_count += 1
                else:
                    entry.last_error = err_msg
                    if entry.attempts >= entry.max_attempts:
                        entry.status = NotificationStatus.FAILED

            except Exception as exc:
                entry.last_error = str(exc)
                if entry.attempts >= entry.max_attempts:
                    entry.status = NotificationStatus.FAILED

        await self.notification_repo.flush_outbox_updates()
        return processed_count
