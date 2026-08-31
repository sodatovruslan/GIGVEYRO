from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.enums.notification import NotificationStatus, NotificationType
from app.models.notification import Notification, NotificationOutbox
from app.models.telegram import TelegramLinkToken
from app.repositories.notification import NotificationRepository
from app.repositories.telegram import TelegramLinkRepository
from app.services.notification import NotificationService
from app.services.telegram import TelegramLinkError, TelegramService
from app.services.telegram_provider import MockTelegramProvider, TelegramDeliveryError


async def _connect(service: TelegramService, account, *, user_id=12345, chat_id=67890):
    raw_token, _ = await service.generate_link_token(account)
    result = await service.consume_link_token(
        raw_token=raw_token,
        telegram_user_id=user_id,
        chat_id=chat_id,
        username="telegram-user",
        first_name="Test",
        telegram_language="en",
    )
    return raw_token, result.connection


@pytest.mark.asyncio
async def test_notification_preferences_and_deduplication(
    db_session, make_account, monkeypatch
):
    monkeypatch.setattr(settings, "TELEGRAM_DELIVERY_ENABLED", True)
    account = await make_account()
    notification_repo = NotificationRepository(db_session)
    telegram_repo = TelegramLinkRepository(db_session)
    provider = MockTelegramProvider()
    service = NotificationService(notification_repo, telegram_repo, provider)
    telegram = TelegramService(telegram_repo)

    raw_token, _ = await _connect(telegram, account)
    persisted = (
        await db_session.execute(
            select(TelegramLinkToken).where(TelegramLinkToken.used_at.is_not(None))
        )
    ).scalar_one()
    assert persisted.token_hash != raw_token
    assert len(persisted.token_hash) == 64

    preference = await notification_repo.get_or_create_preference(account.id)
    await notification_repo.update_preference(preference, {"telegram_enabled": True})
    first = await service.emit_notification(
        account.id,
        NotificationType.DEAL_CREATED,
        "Test Deal",
        "Deal created",
        dedupe_key="unique-deal",
    )
    duplicate = await service.emit_notification(
        account.id,
        NotificationType.DEAL_CREATED,
        "Duplicate",
        "Duplicate message",
        dedupe_key="unique-deal",
    )

    assert first is not None and duplicate is not None and first.id == duplicate.id
    assert await service.process_outbox_batch() == 1
    assert len(provider.sent_messages) == 1
    assert provider.sent_messages[0].chat_id == 67890
    assert provider.sent_messages[0].button_text == "Open in GIGVEYRO"


@pytest.mark.asyncio
async def test_telegram_token_expiry_single_use_and_replacement(db_session, make_account):
    account = await make_account()
    service = TelegramService(TelegramLinkRepository(db_session))
    with pytest.raises(TelegramLinkError):
        await service.consume_link_token(
            raw_token="not-a-real-token",
            telegram_user_id=1,
            chat_id=1,
            username=None,
            first_name=None,
            telegram_language="ru",
        )
    first_raw, _ = await service.generate_link_token(account)
    second_raw, _ = await service.generate_link_token(account)

    with pytest.raises(TelegramLinkError):
        await service.consume_link_token(
            raw_token=first_raw,
            telegram_user_id=1,
            chat_id=1,
            username=None,
            first_name=None,
            telegram_language="ru",
        )

    result = await service.consume_link_token(
        raw_token=second_raw,
        telegram_user_id=2,
        chat_id=2,
        username=None,
        first_name=None,
        telegram_language="tg",
    )
    assert result.language == "tg"
    with pytest.raises(TelegramLinkError):
        await service.consume_link_token(
            raw_token=second_raw,
            telegram_user_id=2,
            chat_id=2,
            username=None,
            first_name=None,
            telegram_language="tg",
        )

    expired_raw, _ = await service.generate_link_token(account)
    expired = await TelegramLinkRepository(db_session).get_token_for_update(expired_raw)
    assert expired is not None
    expired.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.flush()
    with pytest.raises(TelegramLinkError):
        await service.consume_link_token(
            raw_token=expired_raw,
            telegram_user_id=3,
            chat_id=3,
            username=None,
            first_name=None,
            telegram_language="en",
        )


@pytest.mark.asyncio
async def test_blocked_account_cannot_consume_link_token(db_session, make_account):
    account = await make_account()
    service = TelegramService(TelegramLinkRepository(db_session))
    raw_token, _ = await service.generate_link_token(account)
    account.is_active = False
    await db_session.flush()
    with pytest.raises(TelegramLinkError):
        await service.consume_link_token(
            raw_token=raw_token,
            telegram_user_id=44,
            chat_id=44,
            username=None,
            first_name=None,
            telegram_language="ru",
        )


@pytest.mark.asyncio
async def test_notification_outbox_atomicity_and_rollback(db_session, make_account):
    account = await make_account()
    service = NotificationService(
        NotificationRepository(db_session),
        TelegramLinkRepository(db_session),
        MockTelegramProvider(),
    )
    try:
        async with db_session.begin_nested():
            await service.emit_notification(
                account.id,
                NotificationType.DEAL_COMPLETED,
                "Completed",
                "Completed",
                dedupe_key="rollback",
            )
            raise RuntimeError("rollback")
    except RuntimeError:
        pass
    result = await db_session.execute(
        select(Notification).where(Notification.account_id == account.id)
    )
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_mock_provider_retry_and_hidden_notification(
    db_session, make_account, monkeypatch
):
    monkeypatch.setattr(settings, "TELEGRAM_DELIVERY_ENABLED", True)
    account = await make_account()
    notification_repo = NotificationRepository(db_session)
    telegram_repo = TelegramLinkRepository(db_session)
    provider = MockTelegramProvider(should_fail=True)
    service = NotificationService(notification_repo, telegram_repo, provider)
    await _connect(TelegramService(telegram_repo), account, user_id=999, chat_id=888)
    preference = await notification_repo.get_or_create_preference(account.id)
    await notification_repo.update_preference(
        preference, {"telegram_enabled": True, "in_app_enabled": False}
    )
    notification = await service.emit_notification(
        account.id,
        NotificationType.DEPOSIT_CONFIRMED,
        "Deposit",
        "Sensitive amount is not forwarded",
        dedupe_key="deposit",
    )
    assert notification is not None and not notification.in_app_visible
    assert await notification_repo.get_unread_count(account.id) == 0
    assert await service.process_outbox_batch() == 0
    outbox = (
        await db_session.execute(
            select(NotificationOutbox).where(NotificationOutbox.account_id == account.id)
        )
    ).scalar_one()
    assert outbox.status == NotificationStatus.PENDING
    assert outbox.last_error == "temporary_unavailable"
    provider.should_fail = False
    outbox.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.flush()
    assert await service.process_outbox_batch() == 1
    assert "Sensitive amount" not in provider.sent_messages[0].text


@pytest.mark.asyncio
async def test_blocked_bot_disables_delivery(db_session, make_account, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_DELIVERY_ENABLED", True)
    account = await make_account()
    notification_repo = NotificationRepository(db_session)
    telegram_repo = TelegramLinkRepository(db_session)
    _, connection = await _connect(TelegramService(telegram_repo), account)
    preference = await notification_repo.get_or_create_preference(account.id)
    await notification_repo.update_preference(preference, {"telegram_enabled": True})
    service = NotificationService(
        notification_repo,
        telegram_repo,
        MockTelegramProvider(error=TelegramDeliveryError("blocked", retryable=False)),
    )
    await service.emit_notification(
        account.id,
        NotificationType.SECURITY_EVENT,
        "Security",
        "Open the web application",
        dedupe_key="blocked-bot",
    )
    assert await service.process_outbox_batch() == 0
    assert connection.delivery_enabled is False
    assert connection.last_error_category == "blocked"


@pytest.mark.asyncio
async def test_all_domain_notification_events(db_session, make_account):
    account = await make_account()
    repo = NotificationRepository(db_session)
    service = NotificationService(repo, TelegramLinkRepository(db_session), MockTelegramProvider())
    events = [
        NotificationType.DEAL_ACCEPTED,
        NotificationType.DEAL_PAID,
        NotificationType.DEAL_COMPLETED,
        NotificationType.DEAL_CANCELLED,
        NotificationType.APPEAL_OPENED,
        NotificationType.APPEAL_RESOLVED,
        NotificationType.DEPOSIT_CONFIRMED,
        NotificationType.WITHDRAWAL_STATUS_CHANGED,
    ]
    for event in events:
        assert await service.emit_notification(
            account.id, event, "Title", "Message", dedupe_key=event.value
        )
    assert await repo.get_unread_count(account.id) == len(events)
