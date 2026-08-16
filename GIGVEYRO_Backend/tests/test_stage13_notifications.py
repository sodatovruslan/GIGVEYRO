import pytest
import uuid
from datetime import datetime, timezone
from app.enums.notification import NotificationChannel, NotificationStatus, NotificationType
from app.models.notification import NotificationOutbox
from app.repositories.notification import NotificationRepository
from app.repositories.telegram import TelegramLinkRepository
from app.services.notification import NotificationService
from app.services.telegram import TelegramService
from app.services.telegram_provider import MockTelegramProvider


@pytest.mark.asyncio
async def test_notification_preferences_and_deduplication(db_session, make_account):
    acc = await make_account()
    notif_repo = NotificationRepository(db_session)
    tg_repo = TelegramLinkRepository(db_session)
    tg_provider = MockTelegramProvider()

    service = NotificationService(notif_repo, tg_repo, tg_provider)
    tg_service = TelegramService(tg_repo)

    # Generate link code and complete link via hashed verification code
    raw_code, link = await tg_service.generate_link_code(acc.id)
    retrieved_link = await tg_repo.get_by_verification_code(raw_code)
    assert retrieved_link is not None

    await tg_repo.complete_link(retrieved_link, telegram_user_id=12345, chat_id=67890)

    # Enable telegram in preferences
    pref = await notif_repo.get_or_create_preference(acc.id)
    await notif_repo.update_preference(pref, {"telegram_enabled": True})

    # Emit notification with same dedupe key twice
    await service.emit_notification(
        account_id=acc.id,
        type_=NotificationType.DEAL_CREATED,
        title="Test Deal",
        message="Deal created msg",
        dedupe_key="unique_deal_1",
    )
    await service.emit_notification(
        account_id=acc.id,
        type_=NotificationType.DEAL_CREATED,
        title="Test Deal Duplicate",
        message="Deal created msg duplicate",
        dedupe_key="unique_deal_1",
    )

    # Process outbox
    processed = await service.process_outbox_batch()
    assert processed == 1
    assert len(tg_provider.sent_messages) == 1
