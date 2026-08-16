import pytest
import uuid
from datetime import datetime, timezone
from app.enums.notification import NotificationChannel, NotificationStatus, NotificationType
from app.models.notification import NotificationOutbox
from app.repositories.notification import NotificationRepository
from app.repositories.telegram import TelegramLinkRepository
from app.services.notification import NotificationService
from app.services.telegram_provider import MockTelegramProvider


@pytest.mark.asyncio
async def test_notification_deduplication(db_session, make_account):
    acc = await make_account()
    notif_repo = NotificationRepository(db_session)
    tg_repo = TelegramLinkRepository(db_session)
    tg_provider = MockTelegramProvider()

    service = NotificationService(notif_repo, tg_repo, tg_provider)

    # Link telegram account first
    link = await tg_repo.create_or_update_link_code(acc.id, "code123", datetime.now(timezone.utc))
    await tg_repo.complete_link(link, telegram_user_id=12345, chat_id=67890)

    # Enqueue same dedupe key twice
    await service.queue_notification_outbox(
        account_id=acc.id,
        type_=NotificationType.DEAL_CREATED,
        channel=NotificationChannel.TELEGRAM,
        title="Test Deal",
        message="Deal created msg",
        dedupe_key="unique_deal_1",
    )
    await service.queue_notification_outbox(
        account_id=acc.id,
        type_=NotificationType.DEAL_CREATED,
        channel=NotificationChannel.TELEGRAM,
        title="Test Deal Duplicate",
        message="Deal created msg duplicate",
        dedupe_key="unique_deal_1",
    )

    # Process outbox
    processed = await service.process_outbox_batch()
    assert processed == 2
    assert len(tg_provider.sent_messages) == 1  # Only 1 real message sent due to deduplication
