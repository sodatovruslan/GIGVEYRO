import hashlib
import logging
import uuid
from datetime import UTC, datetime, timedelta
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlsplit

from app.core.config import settings
from app.enums.notification import (
    NotificationChannel,
    NotificationMessageKey,
    NotificationStatus,
    NotificationType,
)
from app.models.account import Account
from app.models.notification import Notification, NotificationDelivery, NotificationOutbox
from app.repositories.audit import AuditRepository
from app.repositories.notification import NotificationRepository
from app.repositories.telegram import TelegramLinkRepository
from app.services.audit import AuditService
from app.services.notification_messages import (
    normalize_message_params,
    render_notification_message,
)
from app.services.telegram_provider import TelegramDeliveryError, TelegramProvider
from app.telegram_bot.i18n import notification_label, text

logger = logging.getLogger(__name__)


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
        self._session = notification_repo.session

    @staticmethod
    def generate_dedupe_hash(
        account_id: uuid.UUID, type_: NotificationType, key: str
    ) -> str:
        return hashlib.sha256(f"{account_id}:{type_}:{key}".encode()).hexdigest()

    def _is_type_enabled(self, pref, type_: NotificationType) -> bool:  # noqa: ANN001
        if type_ in {
            NotificationType.DEAL_CREATED,
            NotificationType.DEAL_ACCEPTED,
            NotificationType.DEAL_PAID,
            NotificationType.DEAL_COMPLETED,
            NotificationType.DEAL_CANCELLED,
        }:
            return pref.deal_notifications
        if type_ == NotificationType.DEPOSIT_CONFIRMED:
            return pref.deposit_notifications
        if type_ in {NotificationType.APPEAL_OPENED, NotificationType.APPEAL_RESOLVED}:
            return pref.appeal_notifications
        if type_ == NotificationType.WITHDRAWAL_STATUS_CHANGED:
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
        return await self._emit_notification(
            account_id,
            type_,
            title=title,
            message=message,
            payload=payload,
            dedupe_key=dedupe_key,
        )

    async def emit_semantic_notification(
        self,
        account_id: uuid.UUID,
        type_: NotificationType,
        message_key: NotificationMessageKey,
        message_params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        dedupe_key: str | None = None,
    ) -> Notification | None:
        return await self._emit_notification(
            account_id,
            type_,
            title="",
            message="",
            message_key=message_key,
            message_params=normalize_message_params(message_params),
            payload=payload,
            dedupe_key=dedupe_key,
        )

    async def _emit_notification(
        self,
        account_id: uuid.UUID,
        type_: NotificationType,
        *,
        title: str,
        message: str,
        message_key: NotificationMessageKey | None = None,
        message_params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        dedupe_key: str | None = None,
    ) -> Notification | None:
        pref = await self.notification_repo.get_or_create_preference(account_id)
        if not self._is_type_enabled(pref, type_):
            return None
        dedupe_hash = (
            self.generate_dedupe_hash(account_id, type_, dedupe_key) if dedupe_key else None
        )
        if dedupe_hash and (
            existing := await self.notification_repo.get_by_dedupe_hash(dedupe_hash)
        ):
            return existing

        # The Notification is canonical; visibility and channel delivery are separate.
        notification = await self.notification_repo.create_notification(
            Notification(
                account_id=account_id,
                type=type_,
                title=title,
                message=message,
                message_key=message_key.value if message_key else None,
                message_params=message_params,
                payload=payload,
                dedupe_hash=dedupe_hash,
                is_read=False,
                in_app_visible=pref.in_app_enabled,
            )
        )
        if pref.in_app_enabled:
            await self.notification_repo.create_delivery(
                NotificationDelivery(
                    notification_id=notification.id,
                    channel=NotificationChannel.IN_APP,
                    status=NotificationStatus.SENT,
                    attempts=1,
                    sent_at=datetime.now(UTC),
                )
            )
        if pref.telegram_enabled and settings.TELEGRAM_DELIVERY_ENABLED:
            await self.notification_repo.create_outbox_entry(
                NotificationOutbox(
                    account_id=account_id,
                    notification_id=notification.id,
                    type=type_,
                    title=title,
                    message=message,
                    payload=payload,
                    dedupe_hash=dedupe_hash,
                    status=NotificationStatus.PENDING,
                    max_attempts=settings.TELEGRAM_DELIVERY_MAX_ATTEMPTS,
                )
            )
        return notification

    async def process_outbox_batch(self, limit: int = 50) -> int:
        entries = await self.notification_repo.get_pending_outbox_entries(limit=limit)
        processed = 0
        audit = AuditService(AuditRepository(self._session))
        for entry in entries:
            entry.attempts += 1
            connection = await self.telegram_repo.get_by_account_id(entry.account_id)
            account = await self._session.get(Account, entry.account_id)
            if (
                connection is None
                or not connection.is_linked
                or not connection.delivery_enabled
                or not connection.chat_id
                or account is None
                or not account.is_active
            ):
                entry.status = NotificationStatus.FAILED
                entry.last_error = "recipient_unavailable"
                entry.processed_at = datetime.now(UTC)
                continue

            if entry.notification_id is None:
                # Upgrade compatibility for pre-0026 pending rows.
                canonical = await self.notification_repo.create_notification(
                    Notification(
                        account_id=entry.account_id,
                        type=entry.type,
                        title=entry.title,
                        message=entry.message,
                        payload=entry.payload,
                        in_app_visible=False,
                    )
                )
                entry.notification_id = canonical.id

            delivery = await self.notification_repo.get_telegram_delivery(entry.notification_id)
            if delivery and delivery.status == NotificationStatus.SENT:
                entry.status = NotificationStatus.SENT
                entry.processed_at = delivery.sent_at or datetime.now(UTC)
                continue
            if delivery is None:
                delivery = await self.notification_repo.create_delivery(
                    NotificationDelivery(
                        notification_id=entry.notification_id,
                        telegram_connection_id=connection.id,
                        channel=NotificationChannel.TELEGRAM,
                        status=NotificationStatus.PENDING,
                    )
                )
            delivery.attempts += 1
            language = connection.language
            canonical = await self._session.get(Notification, entry.notification_id)
            if canonical is not None and canonical.message_key:
                fallback_title = notification_label(language, entry.type)
                title, body = render_notification_message(
                    language,
                    canonical.message_key,
                    canonical.message_params,
                    fallback_title=fallback_title,
                    fallback_message=text(language, "details"),
                )
                message = f"{title}\n{body}"
            else:
                # Legacy rows may contain arbitrary historical text. Keep the
                # established safe generic Telegram presentation rather than
                # forwarding unstructured content to another channel.
                message = f"{notification_label(language, entry.type)}\n{text(language, 'details')}"
            try:
                await self.telegram_provider.send_message(
                    connection.chat_id,
                    message,
                    self._web_link(entry.type, account.role.value, entry.payload),
                    text(language, "open_web"),
                )
                now = datetime.now(UTC)
                delivery.status = NotificationStatus.SENT
                delivery.sent_at = now
                delivery.last_error = None
                delivery.last_error_code = None
                entry.status = NotificationStatus.SENT
                entry.processed_at = now
                entry.last_error = None
                connection.last_delivery_success_at = now
                connection.last_error_category = None
                processed += 1
                logger.info("telegram.delivery.success")
            except TelegramDeliveryError as exc:
                delivery.last_error = exc.category
                delivery.last_error_code = exc.category
                entry.last_error = exc.category
                connection.last_error_category = exc.category
                if exc.category in {"blocked", "chat_not_found"}:
                    connection.delivery_enabled = False
                    connection.disabled_at = datetime.now(UTC)
                    delivery.status = NotificationStatus.FAILED
                    entry.status = NotificationStatus.FAILED
                    entry.processed_at = datetime.now(UTC)
                    await audit.log_action(
                        action="telegram.delivery_disabled",
                        entity_type="telegram_connection",
                        actor_account_id=account.id,
                        actor_role=account.role.value,
                        entity_id=str(connection.id),
                        audit_metadata={"reason": exc.category},
                    )
                    logger.warning(
                        "telegram.delivery.failed",
                        extra={"error_category": exc.category},
                    )
                elif exc.retryable and entry.attempts < entry.max_attempts:
                    delay = exc.retry_after or min(300, 2**entry.attempts)
                    entry.next_attempt_at = datetime.now(UTC) + timedelta(seconds=delay)
                    logger.warning(
                        "telegram.delivery.retry",
                        extra={"error_category": exc.category},
                    )
                else:
                    delivery.status = NotificationStatus.FAILED
                    entry.status = NotificationStatus.FAILED
                    entry.processed_at = datetime.now(UTC)
                    logger.warning(
                        "telegram.delivery.failed",
                        extra={"error_category": exc.category},
                    )
        await self.notification_repo.flush_outbox_updates()
        return processed

    @staticmethod
    def _web_link(
        type_: NotificationType, role: str, payload: dict[str, Any] | None
    ) -> str | None:
        base = settings.TELEGRAM_WEB_APP_URL.rstrip("/")
        parsed = urlsplit(base)
        hostname = parsed.hostname
        if parsed.scheme != "https" or not hostname or hostname.lower() == "localhost":
            return None
        try:
            if ip_address(hostname).is_loopback:
                return None
        except ValueError:
            pass
        section = {
            NotificationType.APPEAL_OPENED: "appeals",
            NotificationType.APPEAL_RESOLVED: "appeals",
            NotificationType.WITHDRAWAL_STATUS_CHANGED: "withdrawals",
            NotificationType.PAYOUT_ACTION_REQUIRED: "payouts",
            NotificationType.TREASURY_RISK_CHANGED: "treasury",
        }.get(type_, "deals" if type_.value.startswith("DEAL_") else "notifications")
        return f"{base}/{role}/{section}"
