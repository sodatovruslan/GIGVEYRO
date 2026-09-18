import asyncio
import uuid
from decimal import Decimal

import pytest
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.methods import SendMessage
from sqlalchemy import delete, func, select

from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.db.session import AsyncSessionLocal
from app.enums.account import UserRole
from app.enums.withdrawal import WithdrawalStatus
from app.models.account import Account
from app.models.audit import AuditLog
from app.models.team_lead_withdrawal import TeamLeadWithdrawal
from app.models.telegram import TelegramAccountLink, TelegramLinkToken
from app.repositories.telegram import TelegramLinkRepository
from app.services.telegram import TelegramLinkError, TelegramService
from app.services.telegram_provider import (
    AiogramTelegramProvider,
    MockTelegramProvider,
    TelegramDeliveryError,
    telegram_diagnostics,
)
from app.telegram_bot import keyboards as tg_keyboards
from app.telegram_bot.commands import TelegramCommandService


def _buttons(markup) -> list[tuple[str, str]]:  # noqa: ANN001
    return [(button.text, button.callback_data) for row in markup.inline_keyboard for button in row]


async def _link(commands: TelegramCommandService, account, telegram_user_id: int) -> None:  # noqa: ANN001
    token, _ = await commands.telegram.generate_link_token(account)
    await commands.handle(
        telegram_user_id=telegram_user_id,
        chat_id=telegram_user_id,
        text_value=f"/start {token}",
        telegram_language="en",
    )


def _headers(account) -> dict[str, str]:
    token = create_access_token(account.id, account.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _allow_commands(monkeypatch):
    async def allowed(*args, **kwargs):  # noqa: ANN002, ANN003
        return False

    monkeypatch.setattr("app.telegram_bot.commands.RedisRateLimiter.is_rate_limited", allowed)


@pytest.mark.asyncio
async def test_link_identity_conflict_block_and_relink(db_session, make_account):
    first = await make_account()
    second = await make_account()
    first_service = TelegramService(TelegramLinkRepository(db_session))
    first_token, _ = await first_service.generate_link_token(first)
    result = await first_service.consume_link_token(
        raw_token=first_token,
        telegram_user_id=456,
        chat_id=456,
        username="metadata-only",
        first_name=None,
        telegram_language="ru",
    )
    assert result.connection.telegram_user_id == 456

    second_token, _ = await first_service.generate_link_token(second)
    with pytest.raises(TelegramLinkError):
        await first_service.consume_link_token(
            raw_token=second_token,
            telegram_user_id=456,
            chat_id=456,
            username="renamed",
            first_name=None,
            telegram_language="ru",
        )

    await first_service.disconnect(result.connection, first)
    relink = await first_service.consume_link_token(
        raw_token=second_token,
        telegram_user_id=456,
        chat_id=456,
        username="renamed",
        first_name=None,
        telegram_language="en",
    )
    assert relink.connection.account_id == second.id


@pytest.mark.asyncio
async def test_concurrent_double_consume_has_exactly_one_winner():
    account_id = uuid.uuid4()
    async with AsyncSessionLocal() as session:
        account = Account(
            id=account_id,
            username=f"telegram_race_{uuid.uuid4().hex[:8]}",
            password_hash=hash_password("TelegramRacePassword123"),
            role=UserRole.USER,
            full_name="Telegram Race",
            is_active=True,
        )
        session.add(account)
        await session.flush()
        raw_token, _ = await TelegramService(TelegramLinkRepository(session)).generate_link_token(
            account
        )
        await session.commit()

    async def consume(user_id: int) -> bool:
        async with AsyncSessionLocal() as session:
            try:
                await TelegramService(TelegramLinkRepository(session)).consume_link_token(
                    raw_token=raw_token,
                    telegram_user_id=user_id,
                    chat_id=user_id,
                    username=None,
                    first_name=None,
                    telegram_language="en",
                )
                await session.commit()
                return True
            except TelegramLinkError:
                await session.rollback()
                return False

    try:
        assert sum(await asyncio.gather(consume(9001), consume(9002))) == 1
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(delete(AuditLog).where(AuditLog.actor_account_id == account_id))
            await session.execute(delete(Account).where(Account.id == account_id))
            await session.commit()


@pytest.mark.asyncio
async def test_commands_are_read_only_role_scoped_and_require_active_account(
    db_session, make_account, make_wallet, monkeypatch
):
    await _allow_commands(monkeypatch)
    account = await make_account()
    await make_wallet(account)
    commands = TelegramCommandService(db_session)
    token, _ = await commands.telegram.generate_link_token(account)
    assert (
        "connected"
        in (
            await commands.handle(
                telegram_user_id=88,
                chat_id=99,
                text_value=f"/start {token}",
                telegram_language="en",
            )
        ).lower()
    )
    assert "0.00 USDT" in await commands.handle(
        telegram_user_id=88, chat_id=99, text_value="/balance"
    )
    for language, expected in (
        ("ru", "Язык: RU\nДоставка: включена"),
        ("tg", "Забон: TG\nИрсол: фаъол"),
        ("en", "Language: EN\nDelivery: enabled"),
    ):
        await commands.handle(
            telegram_user_id=88,
            chat_id=99,
            text_value=f"/language {language}",
        )
        assert expected == await commands.handle(
            telegram_user_id=88,
            chat_id=99,
            text_value="/settings",
        )
    assert (
        "unknown"
        in (
            await commands.handle(
                telegram_user_id=88,
                chat_id=99,
                text_value="/withdraw 100",
            )
        ).lower()
    )
    assert (
        "not connected"
        in (
            await commands.handle(
                telegram_user_id=88,
                chat_id=100,
                text_value="/status",
                telegram_language="en",
            )
        ).lower()
    )
    account.is_active = False
    await db_session.flush()
    assert (
        "temporarily unavailable"
        in (await commands.handle(telegram_user_id=88, chat_id=99, text_value="/status")).lower()
    )


async def test_bare_start_points_to_web_login_and_never_asks_for_a_password(db_session):
    """/start with no token must guide the user to the website's own
    Connect Telegram flow (Settings -> Notifications) instead of ever
    prompting for a username/password in the chat itself."""
    commands = TelegramCommandService(db_session)
    reply = await commands.handle(
        telegram_user_id=777, chat_id=777, text_value="/start", telegram_language="en"
    )
    expected_url = f"{settings.TELEGRAM_WEB_APP_URL.rstrip('/')}/login"
    assert expected_url in reply
    assert "never ask for your password" in reply.lower()


async def test_unlinked_user_message_points_to_web_login(db_session):
    """Any command from an account that has never linked Telegram gets the
    same actionable pointer to the website, not a bare 'unlinked' notice."""
    commands = TelegramCommandService(db_session)
    reply = await commands.handle(
        telegram_user_id=778, chat_id=778, text_value="/status", telegram_language="en"
    )
    expected_url = f"{settings.TELEGRAM_WEB_APP_URL.rstrip('/')}/login"
    assert expected_url in reply
    assert "no password is ever needed" in reply.lower()


@pytest.mark.asyncio
async def test_owner_and_merchant_command_boundaries(
    db_session, make_account, make_merchant_wallet, monkeypatch
):
    await _allow_commands(monkeypatch)
    owner = await make_account(role=UserRole.OWNER)
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant)
    commands = TelegramCommandService(db_session)

    owner_token, _ = await commands.telegram.generate_link_token(owner)
    await commands.handle(
        telegram_user_id=501,
        chat_id=501,
        text_value=f"/start {owner_token}",
        telegram_language="en",
    )
    assert (
        "risk"
        in (await commands.handle(telegram_user_id=501, chat_id=501, text_value="/status")).lower()
    )
    assert (
        "unknown"
        in (await commands.handle(telegram_user_id=501, chat_id=501, text_value="/balance")).lower()
    )

    merchant_token, _ = await commands.telegram.generate_link_token(merchant)
    await commands.handle(
        telegram_user_id=502,
        chat_id=502,
        text_value=f"/start {merchant_token}",
        telegram_language="en",
    )
    assert "0.00 USDT" in await commands.handle(
        telegram_user_id=502, chat_id=502, text_value="/balance"
    )
    assert (
        "unknown"
        in (await commands.handle(telegram_user_id=502, chat_id=502, text_value="/risk")).lower()
    )


@pytest.mark.asyncio
async def test_authenticated_connection_api_and_webhook_secret(
    client, db_session, make_account, monkeypatch
):
    account = await make_account()
    monkeypatch.setattr(settings, "TELEGRAM_BOT_ENABLED", True)
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "gigveyro_test_bot")
    response = await client.post("/telegram/link-token", headers=_headers(account))
    assert response.status_code == 200
    body = response.json()
    assert body["deep_link"].startswith("https://t.me/gigveyro_test_bot?start=")
    raw_token = body["deep_link"].split("start=", 1)[1]
    stored = (await db_session.execute(select(TelegramLinkToken))).scalar_one()
    assert stored.token_hash != raw_token

    assert (await client.get("/telegram/connection", headers=_headers(account))).json() == {
        "connected": False,
        "masked_username": None,
        "linked_at": None,
        "language": "ru",
        "delivery_enabled": False,
        "unhealthy_reason": None,
    }
    invalid = await client.post(
        "/telegram/webhook",
        json={"update_id": 1},
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
    )
    assert invalid.status_code == 404

    await _allow_commands(monkeypatch)
    monkeypatch.setattr(settings, "TELEGRAM_BOT_MODE", "webhook")
    secret_type = type(settings.TELEGRAM_WEBHOOK_SECRET)
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", secret_type("safe-test-secret"))
    provider = MockTelegramProvider()
    monkeypatch.setattr("app.api.telegram.get_telegram_provider", lambda: provider)
    valid = await client.post(
        "/telegram/webhook",
        json={
            "update_id": 2,
            "message": {
                "text": f"/start {raw_token}",
                "chat": {"id": 777, "type": "private"},
                "from": {"id": 777, "language_code": "tg", "username": "ignored"},
            },
        },
        headers={"X-Telegram-Bot-Api-Secret-Token": "safe-test-secret"},
    )
    assert valid.status_code == 200
    assert len(provider.sent_messages) == 1
    connection = (await db_session.execute(select(TelegramAccountLink))).scalar_one()
    assert connection.telegram_user_id == 777
    assert connection.language == "tg"

    patch = await client.patch(
        "/telegram/connection",
        json={"language": "en", "delivery_enabled": False},
        headers=_headers(account),
    )
    assert patch.status_code == 200
    assert patch.json()["language"] == "en"
    assert patch.json()["delivery_enabled"] is False
    assert (
        await client.delete("/telegram/connection", headers=_headers(account))
    ).status_code == 204

    actions = set((await db_session.execute(select(AuditLog.action))).scalars())
    assert {
        "telegram.link_token_created",
        "telegram.connected",
        "telegram.language_changed",
        "telegram.delivery_disabled",
        "telegram.disconnected",
    } <= actions


@pytest.mark.asyncio
async def test_role_home_menus_and_cross_role_isolation(db_session, make_account, monkeypatch):
    await _allow_commands(monkeypatch)
    commands = TelegramCommandService(db_session)
    owner = await make_account(role=UserRole.OWNER)
    team_lead = await make_account(role=UserRole.TEAM_LEAD)
    user = await make_account(role=UserRole.USER)
    merchant = await make_account(role=UserRole.MERCHANT)
    await _link(commands, owner, 701)
    await _link(commands, team_lead, 702)
    await _link(commands, user, 703)
    await _link(commands, merchant, 704)

    owner_home = await commands.handle_callback(telegram_user_id=701, chat_id=701, data="home")
    owner_callbacks = {cb for _, cb in _buttons(owner_home.keyboard)}
    assert {"ow_dash", "ow_wd", "ow_tl:1", "ow_risk"} <= owner_callbacks

    tl_home = await commands.handle_callback(telegram_user_id=702, chat_id=702, data="home")
    tl_callbacks = {cb for _, cb in _buttons(tl_home.keyboard)}
    assert {"tl_dash", "tl_team:1", "tl_profit:1", "tl_wd:1"} <= tl_callbacks
    assert not any(cb.startswith("ow_") for cb in tl_callbacks)

    # A non-OWNER account must never reach an OWNER-only screen via callback.
    for telegram_user_id in (702, 703, 704):
        reply = await commands.handle_callback(
            telegram_user_id=telegram_user_id, chat_id=telegram_user_id, data="ow_dash"
        )
        assert "unknown" in reply.lower()

    # USER and MERCHANT must never reach TEAM_LEAD-only screens.
    for telegram_user_id in (703, 704):
        reply = await commands.handle_callback(
            telegram_user_id=telegram_user_id, chat_id=telegram_user_id, data="tl_dash"
        )
        assert "unknown" in reply.lower()


@pytest.mark.asyncio
async def test_team_lead_cannot_view_another_team_leads_withdrawal(
    db_session, make_account, make_wallet, monkeypatch
):
    await _allow_commands(monkeypatch)
    commands = TelegramCommandService(db_session)
    lead_a = await make_account(role=UserRole.TEAM_LEAD)
    lead_b = await make_account(role=UserRole.TEAM_LEAD)
    await make_wallet(lead_a, available=Decimal("50"))
    await make_wallet(lead_b, available=Decimal("50"))
    await _link(commands, lead_a, 711)
    await _link(commands, lead_b, 712)

    withdrawal = TeamLeadWithdrawal(
        public_id="TLW-IDOR01",
        team_lead_id=lead_a.id,
        wallet_id=(await commands._wallet_service().get_wallet_for_account(lead_a.id)).id,
        amount=Decimal("5"),
        destination_type="usdt_trc20_address",
        destination="TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
        status=WithdrawalStatus.PENDING,
        created_by_account_id=lead_a.id,
    )
    db_session.add(withdrawal)
    await db_session.flush()

    reply = await commands.handle_callback(
        telegram_user_id=712, chat_id=712, data=f"tl_wd_d:{withdrawal.id}"
    )
    assert "wrong" in reply.lower()
    assert withdrawal.public_id not in reply
    assert withdrawal.destination not in reply


@pytest.mark.asyncio
async def test_team_lead_withdrawal_full_flow_and_owner_approval(
    db_session, make_account, make_wallet, monkeypatch
):
    await _allow_commands(monkeypatch)
    commands = TelegramCommandService(db_session)
    owner = await make_account(role=UserRole.OWNER)
    team_lead = await make_account(role=UserRole.TEAM_LEAD)
    await make_wallet(team_lead, available=Decimal("50"))
    await _link(commands, owner, 721)
    await _link(commands, team_lead, 722)

    prompt = await commands.handle_callback(telegram_user_id=722, chat_id=722, data="tl_wd_new")
    assert "amount" in prompt.lower()
    amount_reply = await commands.handle(telegram_user_id=722, chat_id=722, text_value="20")
    assert "method" in amount_reply.lower()
    dest_type_reply = await commands.handle_callback(
        telegram_user_id=722, chat_id=722, data="wdflow:dt:usdt_trc20_address"
    )
    assert dest_type_reply.keyboard is not None
    dest_reply = await commands.handle(telegram_user_id=722, chat_id=722, text_value="TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t")
    assert dest_reply.keyboard is not None
    created_reply = await commands.handle_callback(
        telegram_user_id=722, chat_id=722, data="wdflow_go"
    )
    assert "TLW-" in created_reply

    withdrawal = (
        await db_session.execute(
            select(TeamLeadWithdrawal).where(TeamLeadWithdrawal.team_lead_id == team_lead.id)
        )
    ).scalar_one()
    assert withdrawal.status == WithdrawalStatus.PENDING
    assert withdrawal.amount == Decimal("20")

    # Pressing "wdflow_go" again (double submit) must not create a second withdrawal.
    await commands.handle_callback(telegram_user_id=722, chat_id=722, data="wdflow_go")
    total_withdrawals = (
        await db_session.execute(
            select(func.count(TeamLeadWithdrawal.id)).where(
                TeamLeadWithdrawal.team_lead_id == team_lead.id
            )
        )
    ).scalar_one()
    assert total_withdrawals == 1

    ask = await commands.handle_callback(
        telegram_user_id=721, chat_id=721, data=f"a:tlw:{withdrawal.id}:appr"
    )
    assert ask.keyboard is not None
    approved = await commands.handle_callback(
        telegram_user_id=721, chat_id=721, data=f"g:tlw:{withdrawal.id}:appr"
    )
    await db_session.refresh(withdrawal)
    assert withdrawal.status == WithdrawalStatus.APPROVED
    assert "approve" in approved.lower() or withdrawal.status.value in approved.lower()

    await commands.handle_callback(
        telegram_user_id=721, chat_id=721, data=f"a:tlw:{withdrawal.id}:paid"
    )
    await commands.handle_callback(
        telegram_user_id=721, chat_id=721, data=f"g:tlw:{withdrawal.id}:paid"
    )
    await db_session.refresh(withdrawal)
    assert withdrawal.status == WithdrawalStatus.PAID

    actions = set((await db_session.execute(select(AuditLog.action))).scalars())
    assert {"team_lead_withdrawal.approve", "team_lead_withdrawal.mark_paid"} <= actions


@pytest.mark.asyncio
async def test_blocked_account_cannot_use_callback_menu(db_session, make_account, monkeypatch):
    await _allow_commands(monkeypatch)
    commands = TelegramCommandService(db_session)
    account = await make_account(role=UserRole.USER)
    await _link(commands, account, 731)
    account.is_active = False
    await db_session.flush()

    reply = await commands.handle_callback(telegram_user_id=731, chat_id=731, data="u_bal")
    assert "temporarily unavailable" in reply.lower()


@pytest.mark.asyncio
async def test_language_switch_via_callback_updates_settings_screen(
    db_session, make_account, monkeypatch
):
    await _allow_commands(monkeypatch)
    commands = TelegramCommandService(db_session)
    account = await make_account(role=UserRole.USER)
    await _link(commands, account, 741)

    reply = await commands.handle_callback(telegram_user_id=741, chat_id=741, data="lang:ru")
    assert "RU" in reply
    connection = await commands.repo.get_by_account_id(account.id)
    assert connection.language == "ru"


@pytest.mark.asyncio
async def test_owner_accounts_list_paginates(db_session, make_account, monkeypatch):
    await _allow_commands(monkeypatch)
    commands = TelegramCommandService(db_session)
    owner = await make_account(role=UserRole.OWNER)
    await _link(commands, owner, 751)
    for _ in range(tg_keyboards.PAGE_SIZE + 2):
        await make_account(role=UserRole.USER)

    page1 = await commands.handle_callback(telegram_user_id=751, chat_id=751, data="ow_acc:1")
    callbacks = {cb for _, cb in _buttons(page1.keyboard)}
    assert "ow_acc:2" in callbacks


def test_telegram_diagnostics_never_expose_secret(monkeypatch):
    secret_type = type(settings.TELEGRAM_BOT_TOKEN)
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", secret_type("123:do-not-expose"))
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "safe_name")
    diagnostics = telegram_diagnostics()
    assert diagnostics["configured"] is True
    assert "token" not in diagnostics
    assert "123:do-not-expose" not in repr(diagnostics)


class _FailingBot:
    def __init__(self, error: Exception):
        self.error = error

    async def send_message(self, **kwargs):  # noqa: ANN003, ANN201
        raise self.error


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exception", "category", "retryable", "retry_after"),
    [
        (
            TelegramNetworkError(SendMessage(chat_id=1, text="x"), "timeout"),
            "temporary_unavailable",
            True,
            None,
        ),
        (
            TelegramServerError(SendMessage(chat_id=1, text="x"), "server"),
            "temporary_unavailable",
            True,
            None,
        ),
        (
            TelegramRetryAfter(SendMessage(chat_id=1, text="x"), "retry", 7),
            "rate_limited",
            True,
            7,
        ),
        (
            TelegramForbiddenError(SendMessage(chat_id=1, text="x"), "blocked"),
            "blocked",
            False,
            None,
        ),
        (
            TelegramBadRequest(SendMessage(chat_id=1, text="x"), "chat not found"),
            "chat_not_found",
            False,
            None,
        ),
        (
            TelegramBadRequest(SendMessage(chat_id=1, text="x"), "BUTTON_URL_INVALID"),
            "button_url_invalid",
            False,
            None,
        ),
    ],
)
async def test_provider_classifies_delivery_failures(exception, category, retryable, retry_after):  # noqa: ANN001
    provider = AiogramTelegramProvider(bot=_FailingBot(exception))
    with pytest.raises(TelegramDeliveryError) as captured:
        await provider.send_message(1, "safe text")
    assert captured.value.category == category
    assert captured.value.retryable is retryable
    assert captured.value.retry_after == retry_after
