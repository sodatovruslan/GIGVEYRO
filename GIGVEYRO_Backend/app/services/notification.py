import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

from app.enums.notification import NotificationChannel, NotificationStatus, NotificationType
from app.models.notification import Notification, NotificationOutbox
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

    async def queue_notification_outbox(
        self,
        account_id: uuid.UUID,
        type_: NotificationType,
        channel: NotificationChannel,
        title: str,
        message: str,
        payload: dict[str, Any] | None = None,
        dedupe_key: str | None = None,
    ) -> NotificationOutbox:
        dedupe_hash = (
            self.generate_dedupe_hash(account_id, type_, dedupe_key)
            if dedupe_key
            else None
        )
        outbox = NotificationOutbox(
            account_id=account_id,
            channel=channel,
            type=type_,
            title=title,
            message=message,
            payload=payload,
            dedupe_hash=dedupe_hash,
            status=NotificationStatus.PENDING,
        )
        return await self.notification_repo.create_outbox_entry(outbox)

    async def process_outbox_batch(self, limit: int = 50) -> int:
        entries = await self.notification_repo.get_pending_outbox_entries(limit=limit)
        processed_count = 0

        for entry in entries:
            entry.attempts += 1
            try:
                if entry.dedupe_hash:
                    existing = await self.notification_repo.get_by_dedupe_hash(entry.dedupe_hash)
                    if existing:
                        entry.status = NotificationStatus.SENT
                        entry.processed_at = datetime.now(timezone.utc)
                        processed_count += 1
                        continue

                sent_ok = False
                if entry.channel == NotificationChannel.TELEGRAM:
                    tg_link = await self.telegram_repo.get_by_account_id(entry.account_id)
                    if tg_link and tg_link.is_linked and tg_link.chat_id:
                        sent_ok = await self.telegram_provider.send_message(
                            tg_link.chat_id, f"<b>{entry.title}</b>\n{entry.message}"
                        )
                    else:
                        # Fallback/Mark as failed if user not linked
                        entry.last_error = "User not linked to Telegram"

                elif entry.channel == NotificationChannel.IN_APP:
                    sent_ok = True

                if sent_ok:
                    notification = Notification(
                        account_id=entry.account_id,
                        type=entry.type,
                        channel=entry.channel,
                        title=entry.title,
                        message=entry.message,
                        payload=entry.payload,
                        dedupe_hash=entry.dedupe_hash,
                        status=NotificationStatus.SENT,
                        sent_at=datetime.now(timezone.utc),
                    )
                    await self.notification_repo.create_notification(notification)
                    entry.status = NotificationStatus.SENT
                    entry.processed_at = datetime.now(timezone.utc)
                    processed_count += 1
                else:
                    if entry.attempts >= entry.max_attempts:
                        entry.status = NotificationStatus.FAILED

            except Exception as exc:
                entry.last_error = str(exc)
                if entry.attempts >= entry.max_attempts:
                    entry.status = NotificationStatus.FAILED

        return processed_count
