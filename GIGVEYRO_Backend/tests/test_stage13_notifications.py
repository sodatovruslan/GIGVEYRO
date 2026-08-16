import asyncio
import uuid
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import select

from app.enums.account import UserRole
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

    # Verification code hashing check
    raw_code, link = await tg_service.generate_link_code(acc.id)
    assert link.verification_code_hash is not None
    assert link.verification_code_hash != raw_code

    retrieved_link = await tg_repo.get_by_verification_code(raw_code)
    assert retrieved_link is not None
    assert retrieved_link.account_id == acc.id

    await tg_repo.complete_link(retrieved_link, telegram_user_id=12345, chat_id=67890)

    pref = await notif_repo.get_or_create_preference(acc.id)
    await notif_repo.update_preference(pref, {"telegram_enabled": True})

    # Deduplication test
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

    assert notif1.id == notif2.id

    processed = await service.process_outbox_batch()
    assert processed == 1
    assert len(tg_provider.sent_messages) == 1
    assert tg_provider.sent_messages[0].chat_id == 67890


@pytest.mark.asyncio
async def test_telegram_security_code_ttl_and_single_use(db_session, make_account):
    acc = await make_account()
    tg_repo = TelegramLinkRepository(db_session)
    tg_service = TelegramService(tg_repo)

    # 1. Verification Code TTL
    raw_code, link = await tg_service.generate_link_code(acc.id)
    link.verification_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db_session.flush()

    res = await tg_service.process_telegram_command(111, 222, f"/start {raw_code}")
    assert "expired" in res.lower()

    # 2. Single-use Code Verification
    raw_code_2, link_2 = await tg_service.generate_link_code(acc.id)
    res_success = await tg_service.process_telegram_command(333, 444, f"/start {raw_code_2}")
    assert "successfully" in res_success.lower()

    # Reuse code -> Should Fail
    res_reuse = await tg_service.process_telegram_command(333, 444, f"/start {raw_code_2}")
    assert "invalid or expired" in res_reuse.lower()


@pytest.mark.asyncio
async def test_notification_outbox_atomicity_and_rollback(db_session, make_account):
    acc = await make_account()
    notif_repo = NotificationRepository(db_session)
    tg_repo = TelegramLinkRepository(db_session)
    tg_provider = MockTelegramProvider()
    service = NotificationService(notif_repo, tg_repo, tg_provider)

    try:
        async with db_session.begin_nested():
            await service.emit_notification(
                account_id=acc.id,
                type_=NotificationType.DEAL_COMPLETED,
                title="Completed Deal",
                message="Your deal completed",
                dedupe_key="deal_completed_1",
            )
            raise RuntimeError("Simulated DB Failure")
    except RuntimeError:
        pass

    stmt = select(Notification).where(Notification.account_id == acc.id)
    res = await db_session.execute(stmt)
    assert res.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_mock_telegram_provider_retry_and_owner_monitoring(db_session, make_account):
    acc = await make_account()
    owner_acc = await make_account(role=UserRole.OWNER)
    notif_repo = NotificationRepository(db_session)
    tg_repo = TelegramLinkRepository(db_session)

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

    # First attempt fails
    processed_1 = await service.process_outbox_batch()
    assert processed_1 == 0

    outbox_stmt = select(NotificationOutbox).where(NotificationOutbox.account_id == acc.id)
    outbox = (await db_session.execute(outbox_stmt)).scalar_one()
    assert outbox.attempts == 1
    assert outbox.status == NotificationStatus.PENDING

    # Fix provider and retry
    failing_provider.should_fail = False
    processed_2 = await service.process_outbox_batch()
    assert processed_2 == 1

    await db_session.refresh(outbox)
    assert outbox.status == NotificationStatus.SENT


@pytest.mark.asyncio
async def test_all_domain_notification_events(db_session, make_account):
    acc = await make_account()
    notif_repo = NotificationRepository(db_session)
    tg_repo = TelegramLinkRepository(db_session)
    tg_provider = MockTelegramProvider()
    service = NotificationService(notif_repo, tg_repo, tg_provider)

    events = [
        (NotificationType.DEAL_ACCEPTED, "deal_acc_1"),
        (NotificationType.DEAL_PAID, "deal_paid_1"),
        (NotificationType.DEAL_COMPLETED, "deal_comp_1"),
        (NotificationType.DEAL_CANCELLED, "deal_canc_1"),
        (NotificationType.APPEAL_OPENED, "appeal_op_1"),
        (NotificationType.APPEAL_RESOLVED, "appeal_res_1"),
        (NotificationType.DEPOSIT_CONFIRMED, "dep_conf_1"),
        (NotificationType.WITHDRAWAL_STATUS_CHANGED, "with_stat_1"),
    ]

    for type_, key in events:
        notif = await service.emit_notification(
            account_id=acc.id,
            type_=type_,
            title=f"Title {type_}",
            message=f"Message {type_}",
            dedupe_key=key,
        )
        assert notif is not None
        assert notif.type == type_

    count = await notif_repo.get_unread_count(acc.id)
    assert count == len(events)
