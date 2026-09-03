from decimal import Decimal

import pytest

from app.core.config import settings
from app.enums.notification import NotificationMessageKey, NotificationType
from app.repositories.notification import NotificationRepository
from app.repositories.telegram import TelegramLinkRepository
from app.services.notification import NotificationService
from app.services.notification_messages import (
    normalize_message_params,
    notification_message_catalog,
    render_notification_message,
)
from app.services.telegram import TelegramService
from app.services.telegram_provider import MockTelegramProvider


def test_every_semantic_notification_has_ru_en_tg_messages():
    catalog = notification_message_catalog()
    expected = set(NotificationMessageKey)
    assert set(catalog) == {"ru", "en", "tg"}
    for locale in ("ru", "en", "tg"):
        assert set(catalog[locale]) == expected
        assert all(title and body for title, body in catalog[locale].values())


@pytest.mark.parametrize(
    ("locale", "expected"),
    [("ru", "Депозит"), ("en", "Deposit"), ("tg", "Амонати")],
)
def test_semantic_renderer_localizes_and_interpolates(locale, expected):
    title, body = render_notification_message(
        locale,
        NotificationMessageKey.DEPOSIT_CREDITED,
        {"reference": "DEP-42", "amount": Decimal("10.5000"), "currency": "USDT"},
        fallback_title="legacy title",
        fallback_message="legacy body",
    )
    assert title
    assert expected in body
    assert "DEP-42" in body
    assert "10.5000 USDT" in body


def test_unknown_message_key_uses_legacy_fallback():
    assert render_notification_message(
        "en",
        "future.unknown",
        None,
        fallback_title="Legacy title",
        fallback_message="Legacy body",
    ) == ("Legacy title", "Legacy body")


def test_message_params_preserve_decimals_and_reject_sensitive_or_float_values():
    assert normalize_message_params({"amount": Decimal("1.2300")}) == {"amount": "1.2300"}
    with pytest.raises(TypeError):
        normalize_message_params({"amount": 1.23})
    with pytest.raises(ValueError):
        normalize_message_params({"session_token": "do-not-store"})


@pytest.mark.parametrize(
    ("locale", "localized_fragment"),
    [("ru", "одобрен"), ("en", "approved"), ("tg", "тасдиқ")],
)
async def test_telegram_delivery_renders_semantic_message_in_connection_language(
    db_session,
    make_account,
    monkeypatch,
    locale,
    localized_fragment,
):
    monkeypatch.setattr(settings, "TELEGRAM_DELIVERY_ENABLED", True)
    account = await make_account()
    notification_repo = NotificationRepository(db_session)
    telegram_repo = TelegramLinkRepository(db_session)
    telegram = TelegramService(telegram_repo)
    raw_token, _ = await telegram.generate_link_token(account)
    await telegram.consume_link_token(
        raw_token=raw_token,
        telegram_user_id=1001,
        chat_id=2002,
        username=None,
        first_name=None,
        telegram_language=locale,
    )
    preference = await notification_repo.get_or_create_preference(account.id)
    await notification_repo.update_preference(preference, {"telegram_enabled": True})
    provider = MockTelegramProvider()
    service = NotificationService(notification_repo, telegram_repo, provider)

    notification = await service.emit_semantic_notification(
        account.id,
        NotificationType.WITHDRAWAL_STATUS_CHANGED,
        NotificationMessageKey.WITHDRAWAL_APPROVED,
        {"reference": "WD-42"},
        payload={"withdrawal_id": "safe-id"},
        dedupe_key=f"localized-{locale}",
    )

    assert notification is not None
    assert notification.title == "" and notification.message == ""
    assert notification.message_key == NotificationMessageKey.WITHDRAWAL_APPROVED
    assert notification.message_params == {"reference": "WD-42"}
    assert await service.process_outbox_batch() == 1
    delivered = provider.sent_messages[0].text
    assert localized_fragment in delivered
    assert "withdrawal.approved" not in delivered
    assert "WD-42" in delivered
