import asyncio
import uuid
from datetime import datetime, timezone
import pytest
from sqlalchemy import select

from app.enums.notification import NotificationChannel, NotificationStatus, NotificationType
from app.models.notification import Notification, NotificationDelivery, NotificationOutbox, NotificationPreference
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

    # 1. Verification code generation and hashing check
    raw_code, link = await tg_service.generate_link_code(acc.id)
    assert link.verification_code_hash is not None
    assert link.verification_code_hash != raw_code

    retrieved_link = await tg_repo.get_by_verification_code(raw_code)
    assert retrieved_link is not None
    assert retrieved_link.account_id == acc.id

    # Complete link
    await tg_repo.complete_link(retrieved_link, telegram_user_id=12345, chat_id=67890)

    # Enable telegram in preferences
    pref = await notif_repo.get_or_create_preference(acc.id)
    await notif_repo.update_preference(pref, {"telegram_enabled": True})

    # 2. Emit notification with same dedupe key twice
    notif1 = await service.emit_notification(
        account_id=acc.id,
        type_=NotificationType.DEAL_CREATED,
        title="Test Deal",
        message="Deal created msg",
        dedupe_key="unique_deal_1",
    )
    notif2 = await service.emit_notification(
        account_id=acc.id,
        type_=NotificationType.DEAL_CREATED,
        title="Test Deal Duplicate",
        message="Deal created msg duplicate",
        dedupe_key="unique_deal_1",
    )

    # Check deduplication on Notification level
    assert notif1.id == notif2.id

    # Process outbox (Telegram delivery)
    processed = await service.process_outbox_batch()
    assert processed == 1
    assert len(tg_provider.sent_messages) == 1
    assert tg_provider.sent_messages[0].chat_id == 67890
    assert "Test Deal" in tg_provider.sent_messages[0].text


@pytest.mark.asyncio
async def test_notification_outbox_atomicity_and_rollback(db_session, make_account):
    """Test that failed/broken notification outbox causes transaction rollback."""
    acc = await make_account()
    notif_repo = NotificationRepository(db_session)
    tg_repo = TelegramLinkRepository(db_session)
    tg_provider = MockTelegramProvider()
    service = NotificationService(notif_repo, tg_repo, tg_provider)

    try:
        async with db_session.begin_nested():
            # Emit normal notification
            await service.emit_notification(
                account_id=acc.id,
                type_=NotificationType.DEAL_COMPLETED,
                title="Completed Deal",
                message="Your deal completed",
                dedupe_key="deal_completed_1",
            )
            # Intentionally simulate exception in critical operation
            raise RuntimeError("Simulated Database Error During Critical Domain Transaction")
    except RuntimeError:
        pass

    # Verify rollback: no Notification or Outbox record exists
    stmt = select(Notification).where(Notification.account_id == acc.id)
    res = await db_session.execute(stmt)
    assert res.scalar_one_or_none() is None

    outbox_stmt = select(NotificationOutbox).where(NotificationOutbox.account_id == acc.id)
    outbox_res = await db_session.execute(outbox_stmt)
    assert outbox_res.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_mock_telegram_provider_retry_and_failure_logging(db_session, make_account):
    """Test retry mechanism when Telegram provider temporarily fails."""
    acc = await make_account()
    notif_repo = NotificationRepository(db_session)
    tg_repo = TelegramLinkRepository(db_session)
    
    # Provider configured to fail initially
    failing_provider = MockTelegramProvider(should_fail=True)
    service = NotificationService(notif_repo, tg_repo, failing_provider)
    tg_service = TelegramService(tg_repo)

    raw_code, link = await tg_service.generate_link_code(acc.id)
    retrieved_link = await tg_repo.get_by_verification_code(raw_code)
    await tg_repo.complete_link(retrieved_link, telegram_user_id=999, chat_id=888)

    pref = await notif_repo.get_or_create_preference(acc.id)
    await notif_repo.update_preference(pref, {"telegram_enabled": True, "in_app_enabled": False})

    await service.emit_notification(
        account_id=acc.id,
        type_=NotificationType.DEPOSIT_CONFIRMED,
        title="Deposit Confirmed",
        message="100 USDT credited",
        dedupe_key="dep_1",
    )

    # First attempt -> Fail
    processed_1 = await service.process_outbox_batch()
    assert processed_1 == 0

    outbox_stmt = select(NotificationOutbox).where(NotificationOutbox.account_id == acc.id)
    outbox = (await db_session.execute(outbox_stmt)).scalar_one()
    assert outbox.attempts == 1
    assert outbox.status == NotificationStatus.PENDING
    assert "Mock Telegram Provider API Failure" in outbox.last_error

    # Fix provider state -> Second attempt -> Success
    failing_provider.should_fail = False
    processed_2 = await service.process_outbox_batch()
    assert processed_2 == 1

    await db_session.refresh(outbox)
    assert outbox.attempts == 2
    assert outbox.status == NotificationStatus.SENT


@pytest.mark.asyncio
async def test_unread_count_and_read_all(db_session, make_account):
    """Test in-app notification count and read status management."""
    acc = await make_account()
    notif_repo = NotificationRepository(db_session)
    tg_repo = TelegramLinkRepository(db_session)
    tg_provider = MockTelegramProvider()
    service = NotificationService(notif_repo, tg_repo, tg_provider)

    # Emit 3 in-app notifications
    for i in range(3):
        await service.emit_notification(
            account_id=acc.id,
            type_=NotificationType.APPEAL_OPENED,
            title=f"Appeal {i}",
            message=f"Appeal message {i}",
            dedupe_key=f"appeal_{i}",
        )

    count = await notif_repo.get_unread_count(acc.id)
    assert count == 3

    # Mark all as read
    updated_count = await notif_repo.mark_all_as_read(acc.id)
    assert updated_count == 3

    count_after = await notif_repo.get_unread_count(acc.id)
    assert count_after == 0
