from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.enums.account import UserRole
from app.enums.appeal import AppealStatus
from app.enums.deal import DealStatus
from app.enums.invoice import InvoiceStatus
from app.enums.payout import PayoutStatus
from app.enums.withdrawal import WithdrawalDestinationType, WithdrawalStatus
from app.infra.metrics import record_telegram_command
from app.infra.redis_rate_limiter import RedisRateLimiter
from app.models.appeal import DealAppeal
from app.models.deal import Deal
from app.models.merchant_wallet import MerchantWallet
from app.models.notification import Notification
from app.models.payout import PayoutIntent
from app.models.risk import TreasurySnapshotRecord
from app.models.wallet import UserWallet
from app.models.withdrawal import MerchantWithdrawal
from app.repositories.account import AccountRepository
from app.repositories.deal import DealRepository
from app.repositories.deposit import DepositRepository
from app.repositories.invoice import InvoiceRepository
from app.repositories.ledger import LedgerRepository
from app.repositories.notification import NotificationRepository
from app.repositories.payout import PayoutRepository
from app.repositories.realtime import RealtimeOutboxRepository
from app.repositories.risk import RiskRepository
from app.repositories.team_lead_withdrawal import TeamLeadWithdrawalRepository
from app.repositories.telegram import TelegramLinkRepository
from app.repositories.user_withdrawal import UserWithdrawalRepository
from app.repositories.wallet import WalletRepository
from app.repositories.withdrawal import WithdrawalRepository
from app.services.account import AccountService
from app.services.deposit_provider import MockTRC20DepositProvider
from app.services.invoice import (
    InvoiceNotAllowedError,
    InvoiceNotCancellableError,
    InvoiceNotFoundError,
    InvoiceService,
)
from app.services.merchant_statistics import MerchantStatisticsService
from app.services.notification import NotificationService
from app.services.notification_messages import render_notification_message
from app.services.payout_runtime import build_controlled_payout_service
from app.services.realtime import RealtimeEventService
from app.services.risk import RiskGuard, TreasurySnapshotService
from app.services.team_lead import TeamLeadService
from app.services.team_lead_withdrawal import (
    InvalidDestinationError as TLInvalidDestinationError,
)
from app.services.team_lead_withdrawal import (
    InvalidWithdrawalTransitionError as TLInvalidTransitionError,
)
from app.services.team_lead_withdrawal import (
    TeamLeadWithdrawalService,
)
from app.services.team_lead_withdrawal import (
    WithdrawalCreationNotAllowedError as TLWithdrawalCreationNotAllowedError,
)
from app.services.team_lead_withdrawal import (
    WithdrawalNotFoundError as TLWithdrawalNotFoundError,
)
from app.services.telegram import TelegramLinkError, TelegramService
from app.services.telegram_provider import MockTelegramProvider
from app.services.user_withdrawal import UserWithdrawalService
from app.services.user_withdrawal import WithdrawalNotFoundError as UserWithdrawalNotFoundError
from app.services.wallet import InsufficientBalanceError, WalletNotFoundError, WalletService
from app.services.withdrawal import (
    InvalidDestinationError,
    InvalidWithdrawalTransitionError,
    WithdrawalCreationNotAllowedError,
    WithdrawalNotFoundError,
    WithdrawalService,
)
from app.telegram_bot import conversation_state
from app.telegram_bot import keyboards as kb
from app.telegram_bot.i18n import (
    SUPPORTED_LANGUAGES,
    normalize_language,
    notification_label,
    text,
)


class TelegramReply(str):
    """A command/callback reply. Behaves exactly like the plain str this
    module has always returned (so every existing test keeps working
    unmodified), but optionally carries an inline keyboard for the caller
    to attach to the outgoing message."""

    def __new__(cls, value: str, keyboard=None):  # noqa: ANN001
        obj = super().__new__(cls, value)
        obj.keyboard = keyboard
        return obj


_DEST_LABEL_KEY = {
    WithdrawalDestinationType.USDT_TRC20_ADDRESS: "btn_dest_trc20",
    WithdrawalDestinationType.BYBIT_UID: "btn_dest_bybit",
}

# kind -> (owner action audit prefix, owner detail callback prefix, role-menu back target)
_WD_KIND_AUDIT_PREFIX = {
    "wdm": "withdrawal",
    "wdu": "user_withdrawal",
    "tlw": "team_lead_withdrawal",
}


def _web_login_url() -> str:
    return f"{settings.TELEGRAM_WEB_APP_URL.rstrip('/')}/login"


def _fmt_dt(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if value else "-"


def _fmt_money(value) -> str:  # noqa: ANN001
    return f"{value:.2f}"


class TelegramCommandService:
    """Role-aware Telegram command + inline-keyboard menu router. Telegram
    is a UI layer only - every mutating action here calls the same
    repository/service classes the authenticated web API uses, so RBAC,
    ownership checks, state machines, risk gates, and audit logging are
    identical to the web cabinet. Nothing here computes a balance, a
    withdrawal eligibility decision, or a payout amount independently."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = TelegramLinkRepository(session)
        self.telegram = TelegramService(self.repo)
        self.notifications = NotificationRepository(session)
        self.limiter = RedisRateLimiter()
        self.accounts = AccountRepository(session)

    # ------------------------------------------------------------------
    # Service factories - mirror the exact wiring the HTTP routers use for
    # the same operation, so Telegram never diverges from the web cabinet's
    # risk gates / notification / realtime / audit behaviour.
    # ------------------------------------------------------------------

    def _wallet_service(self) -> WalletService:
        return WalletService(
            WalletRepository(self.session), LedgerRepository(self.session), self.accounts
        )

    def _notification_service(self) -> NotificationService:
        return NotificationService(
            NotificationRepository(self.session),
            TelegramLinkRepository(self.session),
            MockTelegramProvider(),
        )

    def _realtime_service(self) -> RealtimeEventService:
        return RealtimeEventService(RealtimeOutboxRepository(self.session))

    def _team_lead_service(self) -> TeamLeadService:
        return TeamLeadService(
            account_repository=self.accounts,
            deal_repository=DealRepository(self.session),
            withdrawal_repository=TeamLeadWithdrawalRepository(self.session),
            wallet_service=self._wallet_service(),
        )

    def _team_lead_withdrawal_service(self) -> TeamLeadWithdrawalService:
        return TeamLeadWithdrawalService(
            withdrawal_repository=TeamLeadWithdrawalRepository(self.session),
            wallet_service=self._wallet_service(),
            account_repository=self.accounts,
            notification_service=self._notification_service(),
            realtime_service=self._realtime_service(),
        )

    def _user_withdrawal_service(self, *, for_creation: bool = False) -> UserWithdrawalService:
        return UserWithdrawalService(
            withdrawal_repository=UserWithdrawalRepository(self.session),
            wallet_service=self._wallet_service(),
            account_repository=self.accounts,
            notification_service=self._notification_service(),
            risk_guard=RiskGuard(RiskRepository(self.session)) if for_creation else None,
            realtime_service=self._realtime_service(),
        )

    def _merchant_withdrawal_service(self, *, for_creation: bool = False) -> WithdrawalService:
        return WithdrawalService(
            withdrawal_repository=WithdrawalRepository(self.session),
            wallet_service=self._wallet_service(),
            account_repository=self.accounts,
            notification_service=self._notification_service(),
            risk_guard=RiskGuard(RiskRepository(self.session)) if for_creation else None,
            controlled_payout=build_controlled_payout_service(self.session)
            if for_creation
            else None,
        )

    def _invoice_service(self) -> InvoiceService:
        return InvoiceService(
            InvoiceRepository(self.session),
            DepositRepository(self.session),
            MockTRC20DepositProvider(),
        )

    def _account_service(self) -> AccountService:
        return AccountService(self.accounts)

    def _treasury_service(self) -> TreasurySnapshotService:
        return TreasurySnapshotService(RiskRepository(self.session))

    def _payout_repo(self) -> PayoutRepository:
        return PayoutRepository(self.session)

    def _statistics_service(self) -> MerchantStatisticsService:
        return MerchantStatisticsService(
            InvoiceRepository(self.session), WithdrawalRepository(self.session)
        )

    async def _audit_log(self, *, action: str, entity_id: str, actor) -> None:  # noqa: ANN001
        from app.repositories.audit import AuditRepository
        from app.services.audit import AuditService

        await AuditService(AuditRepository(self.session)).log_action(
            action=action,
            entity_type=action.split(".", 1)[0],
            entity_id=entity_id,
            actor_account_id=actor.id,
            actor_role=actor.role.value,
        )

    # ------------------------------------------------------------------
    # Text commands (unchanged behaviour - existing tests assert on these)
    # ------------------------------------------------------------------

    async def handle(
        self,
        *,
        telegram_user_id: int,
        chat_id: int,
        text_value: str,
        username: str | None = None,
        first_name: str | None = None,
        telegram_language: str | None = None,
    ) -> str:
        fallback_language = normalize_language(telegram_language)
        raw_parts = text_value.strip().split(maxsplit=1)
        raw_command = raw_parts[0].split("@", 1)[0].lower() if raw_parts else "invalid"
        limited = await self.limiter.is_rate_limited(
            f"telegram-command:{hashlib.sha256(str(telegram_user_id).encode()).hexdigest()}",
            settings.TELEGRAM_COMMAND_RATE_LIMIT_REQUESTS,
            settings.TELEGRAM_COMMAND_RATE_LIMIT_WINDOW_SECONDS,
            fail_mode="fallback",
        )
        if limited:
            record_telegram_command(raw_command, "rate_limited")
            return text(fallback_language, "rate_limited")

        parts = raw_parts
        command = parts[0].split("@", 1)[0].lower() if parts else ""
        argument = parts[1].strip() if len(parts) > 1 else ""
        safe_command = (
            command
            if command
            in {
                "/start",
                "/help",
                "/status",
                "/notifications",
                "/settings",
                "/language",
                "/unlink",
                "/risk",
                "/treasury",
                "/payouts",
                "/withdrawals",
                "/deals",
                "/balance",
                "/menu",
            }
            else "unknown"
        )
        record_telegram_command(safe_command, "received")
        if command == "/start":
            if not argument:
                return text(fallback_language, "welcome", url=_web_login_url())
            try:
                result = await self.telegram.consume_link_token(
                    raw_token=argument,
                    telegram_user_id=telegram_user_id,
                    chat_id=chat_id,
                    username=username,
                    first_name=first_name,
                    telegram_language=telegram_language,
                )
                account = await self.accounts.get_by_id(result.connection.account_id)
                menu = kb.home_menu(result.language, account.role) if account else None
                return TelegramReply(text(result.language, "linked"), menu)
            except TelegramLinkError:
                return text(fallback_language, "invalid_link")

        connection = await self.repo.get_by_telegram_user_id(telegram_user_id, include_account=True)
        if connection is None or connection.chat_id != chat_id:
            return text(fallback_language, "unlinked", url=_web_login_url())
        account = connection.account
        language = connection.language
        if not account.is_active:
            return text(language, "blocked")
        connection.last_seen_at = datetime.now(UTC)

        if command.startswith("/"):
            await conversation_state.clear_pending(telegram_user_id)
        elif not command:
            pass
        else:
            pending = await conversation_state.get_pending(telegram_user_id)
            if pending:
                return await self._handle_flow_text(
                    pending, telegram_user_id, account, language, text_value.strip()
                )

        if command == "/help":
            return self._help(language, account.role)
        if command == "/menu":
            return TelegramReply(
                text(language, "main_menu_title", role=account.role.value.upper()),
                kb.home_menu(language, account.role),
            )
        if command == "/status":
            return await self._status(account.id, account.role, language)
        if command == "/notifications":
            return await self._latest_notifications(account.id, language)
        if command == "/settings":
            return text(
                language,
                "settings",
                language=language.upper(),
                delivery=text(language, "enabled" if connection.delivery_enabled else "disabled"),
            )
        if command == "/language":
            requested = argument.lower()
            if requested not in SUPPORTED_LANGUAGES:
                return text(language, "language_help")
            await self.telegram.change_language(connection, account, requested)
            return text(requested, "language_changed")
        if command == "/unlink":
            if argument.lower() != "confirm":
                return text(language, "unlink_confirm")
            await self.telegram.disconnect(connection, account)
            return text(language, "unlinked_ok")
        if command == "/deals":
            return await self._deals(account.id, account.role, language)
        if command == "/balance" and account.role in {UserRole.USER, UserRole.MERCHANT}:
            return await self._balance(account.id, account.role, language)
        if command == "/withdrawals" and account.role in {UserRole.MERCHANT, UserRole.OWNER}:
            return await self._withdrawals(account.id, account.role, language)
        if command in {"/risk", "/treasury"} and account.role == UserRole.OWNER:
            return await self._risk(language)
        if command == "/payouts" and account.role == UserRole.OWNER:
            return await self._payouts(language)
        return text(language, "unknown")

    @staticmethod
    def _help(language: str, role: UserRole) -> str:
        base = text(language, "help")
        extra = {
            UserRole.OWNER: "/risk /treasury /payouts /withdrawals /deals /menu",
            UserRole.MERCHANT: "/balance /deals /withdrawals /menu",
            UserRole.USER: "/balance /deals /menu",
            UserRole.TEAM_LEAD: "/menu",
        }[role]
        return f"{base}\n{extra}"

    async def _latest_notifications(self, account_id, language: str) -> str:  # noqa: ANN001
        rows = (
            (
                await self.session.execute(
                    select(Notification)
                    .where(Notification.account_id == account_id)
                    .order_by(Notification.created_at.desc())
                    .limit(5)
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            return text(language, "none")
        items = []
        for item in rows:
            fallback = notification_label(language, item.type)
            title, _ = render_notification_message(
                language,
                item.message_key,
                item.message_params,
                fallback_title=fallback,
                fallback_message="",
            )
            items.append(f"• {title}")
        return text(language, "notifications", items="\n".join(items))

    async def _status(self, account_id, role: UserRole, language: str) -> str:  # noqa: ANN001
        unread = await self.notifications.get_unread_count(account_id)
        header = text(language, "status", role=role.value.upper(), unread=unread)
        if role == UserRole.OWNER:
            open_appeals = (
                await self.session.execute(
                    select(func.count(DealAppeal.id)).where(
                        DealAppeal.status.in_({AppealStatus.OPEN, AppealStatus.UNDER_REVIEW})
                    )
                )
            ).scalar_one()
            return "\n".join(
                (
                    header,
                    await self._risk(language),
                    await self._payouts(language),
                    text(language, "appeals", count=open_appeals),
                )
            )
        if role == UserRole.TEAM_LEAD:
            return header
        summaries = [
            header,
            await self._balance(account_id, role, language),
            await self._deals(account_id, role, language),
        ]
        if role == UserRole.MERCHANT:
            summaries.append(await self._withdrawals(account_id, role, language))
        return "\n".join(summaries)

    async def _balance(self, account_id, role: UserRole, language: str) -> str:  # noqa: ANN001
        model = UserWallet if role == UserRole.USER else MerchantWallet
        wallet = (
            await self.session.execute(select(model).where(model.account_id == account_id))
        ).scalar_one_or_none()
        value = wallet.available_balance if wallet else Decimal("0")
        return text(language, "balance", available=f"{value:.2f}")

    async def _deals(self, account_id, role: UserRole, language: str) -> str:  # noqa: ANN001
        query = select(func.count(Deal.id)).where(
            Deal.status.notin_({DealStatus.COMPLETED, DealStatus.CANCELLED, DealStatus.EXPIRED})
        )
        if role == UserRole.USER:
            query = query.where(Deal.user_id == account_id)
        elif role == UserRole.MERCHANT:
            query = query.where(Deal.merchant_id == account_id)
        count = (await self.session.execute(query)).scalar_one()
        return text(language, "deals", count=count)

    async def _withdrawals(self, account_id, role: UserRole, language: str) -> str:  # noqa: ANN001
        query = select(func.count(MerchantWithdrawal.id)).where(
            MerchantWithdrawal.status.in_({WithdrawalStatus.PENDING, WithdrawalStatus.APPROVED})
        )
        if role == UserRole.MERCHANT:
            query = query.where(MerchantWithdrawal.merchant_id == account_id)
        count = (await self.session.execute(query)).scalar_one()
        return text(language, "withdrawals", count=count)

    async def _risk(self, language: str) -> str:
        latest = (
            await self.session.execute(
                select(TreasurySnapshotRecord)
                .order_by(TreasurySnapshotRecord.generated_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return text(language, "risk", status=latest.risk_status if latest else "UNKNOWN")

    async def _payouts(self, language: str) -> str:
        count = (
            await self.session.execute(
                select(func.count(PayoutIntent.id)).where(
                    PayoutIntent.status.in_(
                        {
                            PayoutStatus.RISK_REVIEW.value,
                            PayoutStatus.APPROVED.value,
                            PayoutStatus.QUEUED.value,
                            PayoutStatus.RECONCILIATION_REQUIRED.value,
                        }
                    )
                )
            )
        ).scalar_one()
        return text(language, "payouts", count=count)

    # ------------------------------------------------------------------
    # Callback (inline-keyboard) entry point
    # ------------------------------------------------------------------

    async def handle_callback(
        self,
        *,
        telegram_user_id: int,
        chat_id: int,
        data: str,
        username: str | None = None,
        first_name: str | None = None,
        telegram_language: str | None = None,
    ) -> TelegramReply | None:
        fallback_language = normalize_language(telegram_language)
        limited = await self.limiter.is_rate_limited(
            f"telegram-callback:{hashlib.sha256(str(telegram_user_id).encode()).hexdigest()}",
            settings.TELEGRAM_COMMAND_RATE_LIMIT_REQUESTS,
            settings.TELEGRAM_COMMAND_RATE_LIMIT_WINDOW_SECONDS,
            fail_mode="fallback",
        )
        if limited:
            return TelegramReply(text(fallback_language, "rate_limited"))

        connection = await self.repo.get_by_telegram_user_id(telegram_user_id, include_account=True)
        if connection is None or connection.chat_id != chat_id:
            return TelegramReply(text(fallback_language, "unlinked", url=_web_login_url()))
        account = connection.account
        language = connection.language
        if not account.is_active:
            return TelegramReply(text(language, "blocked"))
        connection.last_seen_at = datetime.now(UTC)

        if not (data.startswith("wdflow") or data.startswith("invflow")):
            await conversation_state.clear_pending(telegram_user_id)

        try:
            return await self._dispatch_callback(data, telegram_user_id, account, language)
        except (
            WalletNotFoundError,
            TLWithdrawalNotFoundError,
            WithdrawalNotFoundError,
            UserWithdrawalNotFoundError,
            InvoiceNotFoundError,
        ):
            return TelegramReply(
                text(language, "error_generic"), kb.home_menu(language, account.role)
            )

    async def _dispatch_callback(  # noqa: C901, PLR0911, PLR0912
        self,
        data: str,
        tg_user_id: int,
        account,
        language: str,  # noqa: ANN001
    ) -> TelegramReply | None:
        role = account.role

        if data == "noop":
            return None
        if data == "home":
            return TelegramReply(
                text(language, "main_menu_title", role=role.value.upper()),
                kb.home_menu(language, role),
            )
        if data.startswith("notif:"):
            return await self._screen_notifications(int(data.split(":")[1]), account, language)
        if data == "settings":
            return await self._screen_settings(account, language)
        if data == "set_lang":
            return TelegramReply(text(language, "lang_picker_title"), kb.language_menu(language))
        if data.startswith("lang:"):
            requested = data.split(":")[1]
            connection = await self.repo.get_by_telegram_user_id(tg_user_id, include_account=True)
            await self.telegram.change_language(connection, account, requested)
            return await self._screen_settings(account, requested)
        if data == "set_delivery":
            connection = await self.repo.get_by_telegram_user_id(tg_user_id, include_account=True)
            key = (
                "confirm_toggle_delivery_off"
                if connection.delivery_enabled
                else "confirm_toggle_delivery_on"
            )
            return TelegramReply(
                text(language, key), kb.confirm_keyboard(language, "set_delivery_go", "settings")
            )
        if data == "set_delivery_go":
            connection = await self.repo.get_by_telegram_user_id(tg_user_id, include_account=True)
            await self.telegram.change_delivery(
                connection, account, not connection.delivery_enabled
            )
            return await self._screen_settings(account, language)
        if data == "set_unlink":
            return TelegramReply(
                text(language, "confirm_unlink"),
                kb.confirm_keyboard(language, "set_unlink_go", "settings"),
            )
        if data == "set_unlink_go":
            connection = await self.repo.get_by_telegram_user_id(tg_user_id, include_account=True)
            await self.telegram.disconnect(connection, account)
            await conversation_state.clear_pending(tg_user_id)
            return TelegramReply(text(language, "unlinked_ok"))

        if data.startswith("wdflow") or data.startswith("invflow"):
            return await self._dispatch_flow_callback(data, tg_user_id, account, language)

        if role == UserRole.TEAM_LEAD:
            reply = await self._dispatch_team_lead(data, tg_user_id, account, language)
            if reply is not _UNHANDLED:
                return reply
        if role == UserRole.OWNER:
            reply = await self._dispatch_owner(data, account, language)
            if reply is not _UNHANDLED:
                return reply
        if role == UserRole.USER:
            reply = await self._dispatch_user(data, tg_user_id, account, language)
            if reply is not _UNHANDLED:
                return reply
        if role == UserRole.MERCHANT:
            reply = await self._dispatch_merchant(data, tg_user_id, account, language)
            if reply is not _UNHANDLED:
                return reply

        return TelegramReply(text(language, "unknown"), kb.home_menu(language, role))

    # ------------------------------------------------------------------
    # Common screens
    # ------------------------------------------------------------------

    async def _screen_notifications(self, page: int, account, language: str) -> TelegramReply:  # noqa: ANN001
        limit = kb.PAGE_SIZE
        rows = await NotificationRepository(self.session).list_for_account(
            account.id, limit=limit + 1, offset=(page - 1) * limit
        )
        has_next = len(rows) > limit
        rows = rows[:limit]
        if not rows:
            body = text(language, "empty_list")
        else:
            items = []
            for item in rows:
                fallback = notification_label(language, item.type)
                title, _ = render_notification_message(
                    language,
                    item.message_key,
                    item.message_params,
                    fallback_title=fallback,
                    fallback_message="",
                )
                items.append(f"• {title} ({_fmt_dt(item.created_at)})")
            body = "\n".join(items)
        keyboard = kb.with_nav(
            language, [kb.prev_next_row(language, "notif", page, has_next)], back="home"
        )
        return TelegramReply(body, keyboard)

    async def _screen_settings(self, account, language: str) -> TelegramReply:  # noqa: ANN001
        connection = await self.repo.get_by_account_id(account.id)
        connected = connection is not None and connection.is_linked
        body = text(
            language,
            "settings_body",
            status=text(language, "connected_yes" if connected else "connected_no"),
            language=language.upper(),
            delivery=text(
                language, "enabled" if (connection and connection.delivery_enabled) else "disabled"
            ),
        )
        keyboard = kb.settings_menu(
            language,
            connected=connected,
            delivery_enabled=bool(connection and connection.delivery_enabled),
        )
        return TelegramReply(body, keyboard)

    # ------------------------------------------------------------------
    # TEAM_LEAD screens
    # ------------------------------------------------------------------

    async def _dispatch_team_lead(self, data: str, tg_user_id: int, account, language: str):  # noqa: ANN001, ANN201
        if data == "tl_dash":
            summary = await self._team_lead_service().dashboard(account.id)
            body = text(
                language,
                "tl_dashboard_body",
                available=_fmt_money(summary.profit_available),
                pending=_fmt_money(summary.profit_pending_withdrawal),
                team_size=summary.team_size,
                deal_count=summary.deal_count,
                volume=_fmt_money(summary.deal_volume),
            )
            return TelegramReply(body, kb.with_nav(language, [], back="home"))

        if data.startswith("tl_team:"):
            page = int(data.split(":")[1])
            items, total = await self._team_lead_service().list_team(
                account.id,
                is_active=None,
                search=None,
                limit=kb.PAGE_SIZE,
                offset=(page - 1) * kb.PAGE_SIZE,
            )
            body = (
                text(language, "empty_list")
                if not items
                else "\n".join(
                    text(
                        language,
                        "team_member_item",
                        full_name=m.full_name,
                        username=m.username,
                        status=text(language, "enabled" if m.is_active else "disabled"),
                    )
                    for m in items
                )
            )
            keyboard = kb.with_nav(
                language,
                [kb.pagination_row(language, "tl_team", page, kb.total_pages(total))],
                back="home",
            )
            return TelegramReply(body, keyboard)

        if data.startswith("tl_profit:"):
            page = int(data.split(":")[1])
            items, total = await self._wallet_service().get_ledger_for_account(
                account.id,
                entry_type=None,
                date_from=None,
                date_to=None,
                limit=kb.PAGE_SIZE,
                offset=(page - 1) * kb.PAGE_SIZE,
            )
            body = (
                text(language, "empty_list")
                if not items
                else "\n".join(
                    text(
                        language,
                        "profit_ledger_item",
                        created=_fmt_dt(entry.created_at),
                        amount=_fmt_money(entry.amount),
                    )
                    for entry in items
                )
            )
            keyboard = kb.with_nav(
                language,
                [kb.pagination_row(language, "tl_profit", page, kb.total_pages(total))],
                back="home",
            )
            return TelegramReply(body, keyboard)

        if data.startswith("tl_wd:"):
            return await self._list_withdrawals_screen(
                account,
                language,
                page=int(data.split(":")[1]),
                kind="tl",
                back="home",
            )
        if data.startswith("tl_wd_d:"):
            wid = _parse_uuid(data.split(":")[1])
            if wid is None:
                return TelegramReply(
                    text(language, "error_generic"), kb.home_menu(language, account.role)
                )
            w = await self._team_lead_withdrawal_service().get_for_team_lead(account.id, wid)
            return self._withdrawal_detail_reply(
                w,
                language,
                back="tl_wd:1",
                cancel_ask=f"tl_wd_cancel_ask:{w.id}"
                if w.status == WithdrawalStatus.PENDING
                else None,
            )
        if data.startswith("tl_wd_cancel_ask:"):
            wid = _parse_uuid(data.split(":")[1])
            w = (
                await self._team_lead_withdrawal_service().get_for_team_lead(account.id, wid)
                if wid
                else None
            )
            if w is None:
                return TelegramReply(
                    text(language, "error_generic"), kb.with_nav(language, [], back="tl_wd:1")
                )
            return TelegramReply(
                text(language, "confirm_cancel_withdrawal", public_id=w.public_id),
                kb.confirm_keyboard(language, f"tl_wd_cancel_go:{w.id}", f"tl_wd_d:{w.id}"),
            )
        if data.startswith("tl_wd_cancel_go:"):
            wid = _parse_uuid(data.split(":")[1])
            w = await self._team_lead_withdrawal_service().cancel_by_team_lead(account.id, wid)
            return TelegramReply(
                text(language, "withdrawal_cancelled", public_id=w.public_id),
                kb.with_nav(language, [], back="tl_wd:1"),
            )
        if data == "tl_wd_new":
            await conversation_state.set_pending(tg_user_id, {"flow": "wd_amount", "kind": "tl"})
            return TelegramReply(
                text(language, "prompt_withdrawal_amount"), kb.flow_cancel_keyboard(language)
            )

        return _UNHANDLED

    # ------------------------------------------------------------------
    # OWNER screens
    # ------------------------------------------------------------------

    async def _dispatch_owner(self, data: str, account, language: str):  # noqa: ANN001, ANN201, C901, PLR0911, PLR0912
        if data == "ow_dash":
            unread = await self.notifications.get_unread_count(account.id)
            open_appeals = (
                await self.session.execute(
                    select(func.count(DealAppeal.id)).where(
                        DealAppeal.status.in_({AppealStatus.OPEN, AppealStatus.UNDER_REVIEW})
                    )
                )
            ).scalar_one()
            payouts = (
                await self.session.execute(
                    select(func.count(PayoutIntent.id)).where(
                        PayoutIntent.status.in_(
                            {
                                PayoutStatus.RISK_REVIEW.value,
                                PayoutStatus.APPROVED.value,
                                PayoutStatus.QUEUED.value,
                                PayoutStatus.RECONCILIATION_REQUIRED.value,
                            }
                        )
                    )
                )
            ).scalar_one()
            snapshot = await self._treasury_service().current()
            body = text(
                language,
                "ow_dashboard_body",
                unread=unread,
                appeals=open_appeals,
                payouts=payouts,
                risk=snapshot.risk_status.value,
            )
            return TelegramReply(body, kb.with_nav(language, [], back="home"))

        if data.startswith("ow_acc:"):
            page = int(data.split(":")[1])
            items, total = await self._account_service().list_accounts(
                role=None,
                is_active=None,
                search=None,
                limit=kb.PAGE_SIZE,
                offset=(page - 1) * kb.PAGE_SIZE,
            )
            items = [a for a in items if a.role != UserRole.OWNER]
            rows = [
                (
                    text(
                        language,
                        "account_list_item",
                        username=a.username,
                        role=a.role.value,
                        status=text(language, "enabled" if a.is_active else "disabled"),
                    ),
                    f"ow_acc_d:{a.id}",
                )
                for a in items
            ]
            keyboard = kb.list_keyboard(
                language,
                item_callbacks=rows,
                page_prefix="ow_acc",
                page=page,
                total_items=total,
                back="home",
            )
            return TelegramReply(text(language, "btn_accounts"), keyboard)
        if data.startswith("ow_acc_d:"):
            aid = _parse_uuid(data.split(":")[1])
            target = await self._account_service().get_managed_account(aid) if aid else None
            if target is None:
                return TelegramReply(
                    text(language, "error_generic"), kb.with_nav(language, [], back="ow_acc:1")
                )
            body = text(
                language,
                "account_card",
                username=target.username,
                role=target.role.value,
                status=text(language, "enabled" if target.is_active else "disabled"),
                full_name=target.full_name,
                created=_fmt_dt(target.created_at),
            )
            return TelegramReply(body, kb.with_nav(language, [], back="ow_acc:1"))

        if data.startswith("ow_deals:"):
            page = int(data.split(":")[1])
            items = await DealRepository(self.session).list_all(
                status=None,
                merchant_id=None,
                user_id=None,
                search=None,
                date_from=None,
                date_to=None,
                limit=kb.PAGE_SIZE,
                offset=(page - 1) * kb.PAGE_SIZE,
            )
            total = await DealRepository(self.session).count_all(
                status=None,
                merchant_id=None,
                user_id=None,
                search=None,
                date_from=None,
                date_to=None,
            )
            rows = [
                (
                    text(
                        language,
                        "deal_list_item",
                        public_id=d.public_id,
                        amount_tjs=_fmt_money(d.amount_tjs),
                        status=d.status.value,
                    ),
                    f"ow_deal_d:{d.id}",
                )
                for d in items
            ]
            keyboard = kb.list_keyboard(
                language,
                item_callbacks=rows,
                page_prefix="ow_deals",
                page=page,
                total_items=total,
                back="home",
            )
            return TelegramReply(text(language, "btn_deals"), keyboard)
        if data.startswith("ow_deal_d:"):
            did = _parse_uuid(data.split(":")[1])
            d = await DealRepository(self.session).get_by_id(did) if did else None
            if d is None:
                return TelegramReply(
                    text(language, "error_generic"), kb.with_nav(language, [], back="ow_deals:1")
                )
            body = text(
                language,
                "deal_card",
                public_id=d.public_id,
                amount_tjs=_fmt_money(d.amount_tjs),
                status=d.status.value,
                created=_fmt_dt(d.created_at),
            )
            return TelegramReply(body, kb.with_nav(language, [], back="ow_deals:1"))

        if data == "ow_wd":
            return TelegramReply(
                text(language, "btn_withdrawals"), kb.owner_withdrawals_menu(language)
            )
        if data.startswith("ow_wdm:"):
            return await self._owner_withdrawal_list(
                language, kind="wdm", page=int(data.split(":")[1])
            )
        if data.startswith("ow_wdu:"):
            return await self._owner_withdrawal_list(
                language, kind="wdu", page=int(data.split(":")[1])
            )
        if data.startswith("ow_wdm_d:") or data.startswith("ow_wdu_d:"):
            kind = "wdm" if data.startswith("ow_wdm_d:") else "wdu"
            wid = _parse_uuid(data.split(":")[1])
            return await self._owner_withdrawal_detail(language, kind, wid)

        if data.startswith("ow_tl:"):
            page = int(data.split(":")[1])
            items, total = await self._account_service().list_accounts(
                role=UserRole.TEAM_LEAD,
                is_active=None,
                search=None,
                limit=kb.PAGE_SIZE,
                offset=(page - 1) * kb.PAGE_SIZE,
            )
            rows = []
            for lead in items:
                _, _, team_size = await self._team_lead_stats(lead.id)
                rows.append(
                    (
                        text(
                            language, "team_lead_item", username=lead.username, team_size=team_size
                        ),
                        f"ow_tl_d:{lead.id}",
                    )
                )
            keyboard = kb.list_keyboard(
                language,
                item_callbacks=rows,
                page_prefix="ow_tl",
                page=page,
                total_items=total,
                back="home",
            )
            return TelegramReply(text(language, "btn_team_leads"), keyboard)
        if data.startswith("ow_tl_d:"):
            lid = _parse_uuid(data.split(":")[1])
            lead = await self.accounts.get_by_id(lid) if lid else None
            if lead is None or lead.role != UserRole.TEAM_LEAD:
                return TelegramReply(
                    text(language, "error_generic"), kb.with_nav(language, [], back="ow_tl:1")
                )
            summary = await self._team_lead_service().dashboard(lead.id)
            body = text(
                language,
                "tl_dashboard_body",
                available=_fmt_money(summary.profit_available),
                pending=_fmt_money(summary.profit_pending_withdrawal),
                team_size=summary.team_size,
                deal_count=summary.deal_count,
                volume=_fmt_money(summary.deal_volume),
            )
            keyboard = kb.with_nav(
                language,
                [[kb.button(text(language, "btn_my_withdrawals"), f"ow_tlw:{lead.id}:1")]],
                back="ow_tl:1",
            )
            return TelegramReply(body, keyboard)
        if data.startswith("ow_tlw:"):
            _, lid_raw, page_raw = data.split(":")
            lid = _parse_uuid(lid_raw)
            page = int(page_raw)
            lead = await self.accounts.get_by_id(lid) if lid else None
            if lead is None or lead.role != UserRole.TEAM_LEAD:
                return TelegramReply(
                    text(language, "error_generic"), kb.with_nav(language, [], back="ow_tl:1")
                )
            items, total = await self._team_lead_withdrawal_service().list_for_owner(
                status=None,
                team_lead_id=lead.id,
                search=None,
                date_from=None,
                date_to=None,
                limit=kb.PAGE_SIZE,
                offset=(page - 1) * kb.PAGE_SIZE,
            )
            rows = [
                (
                    text(
                        language,
                        "wd_list_item",
                        public_id=w.public_id,
                        amount=_fmt_money(w.amount),
                        currency=w.currency.value,
                        status=w.status.value,
                    ),
                    f"ow_tlw_d:{w.id}",
                )
                for w in items
            ]
            keyboard = kb.list_keyboard(
                language,
                item_callbacks=rows,
                page_prefix=f"ow_tlw:{lead.id}",
                page=page,
                total_items=total,
                back=f"ow_tl_d:{lead.id}",
            )
            return TelegramReply(text(language, "btn_my_withdrawals"), keyboard)
        if data.startswith("ow_tlw_d:"):
            wid = _parse_uuid(data.split(":")[1])
            return await self._owner_withdrawal_detail(language, "tlw", wid)

        if data.startswith("ow_payouts:"):
            page = int(data.split(":")[1])
            items, total = await self._payout_repo().list_intents(
                status=None, limit=kb.PAGE_SIZE, offset=(page - 1) * kb.PAGE_SIZE
            )
            rows = [
                (
                    text(
                        language,
                        "payout_list_item",
                        public_id=str(p.id)[:8],
                        amount=_fmt_money(p.amount),
                        status=p.status,
                    ),
                    f"ow_po_d:{p.id}",
                )
                for p in items
            ]
            keyboard = kb.list_keyboard(
                language,
                item_callbacks=rows,
                page_prefix="ow_payouts",
                page=page,
                total_items=total,
                back="home",
            )
            return TelegramReply(text(language, "btn_payouts"), keyboard)
        if data.startswith("ow_po_d:"):
            pid = _parse_uuid(data.split(":")[1])
            p = await self._payout_repo().get(pid) if pid else None
            if p is None:
                return TelegramReply(
                    text(language, "error_generic"), kb.with_nav(language, [], back="ow_payouts:1")
                )
            body = text(
                language,
                "payout_card",
                public_id=str(p.id)[:8],
                amount=_fmt_money(p.amount),
                status=p.status,
                created=_fmt_dt(p.created_at),
            )
            return TelegramReply(body, kb.with_nav(language, [], back="ow_payouts:1"))

        if data == "ow_risk":
            snapshot = await self._treasury_service().current()
            body = text(
                language,
                "ow_risk_body",
                status=snapshot.risk_status.value,
                coverage=snapshot.coverage_ratio_bps
                if snapshot.coverage_ratio_bps is not None
                else "-",
                deficit=_fmt_money(snapshot.reserve_deficit_usdt),
            )
            return TelegramReply(body, kb.with_nav(language, [], back="home"))
        if data == "ow_treasury":
            snapshot = await self._treasury_service().current()
            body = text(
                language,
                "ow_treasury_body",
                external=_fmt_money(snapshot.external_bybit_usdt),
                user_liability=_fmt_money(snapshot.internal_user_liability_usdt),
                merchant_liability=_fmt_money(snapshot.merchant_liability_usdt),
                required=_fmt_money(snapshot.required_reserve_usdt),
            )
            return TelegramReply(body, kb.with_nav(language, [], back="home"))

        if data.startswith("a:") or data.startswith("g:"):
            return await self._owner_withdrawal_action(data, account, language)

        return _UNHANDLED

    async def _team_lead_stats(self, team_lead_id) -> tuple[int, Decimal, int]:  # noqa: ANN001
        count, volume, _ = await DealRepository(self.session).team_stats(team_lead_id)
        _, total = await self._team_lead_service().list_team(
            team_lead_id, is_active=None, search=None, limit=1, offset=0
        )
        return count, volume, total

    async def _owner_withdrawal_list(self, language: str, *, kind: str, page: int) -> TelegramReply:
        limit, offset = kb.PAGE_SIZE, (page - 1) * kb.PAGE_SIZE
        if kind == "wdm":
            items, total = await self._merchant_withdrawal_service().list_for_owner(
                status=None,
                merchant_id=None,
                search=None,
                date_from=None,
                date_to=None,
                limit=limit,
                offset=offset,
            )
            detail_prefix = "ow_wdm_d"
        else:
            items, total = await self._user_withdrawal_service().list_for_owner(
                status=None,
                user_id=None,
                search=None,
                date_from=None,
                date_to=None,
                limit=limit,
                offset=offset,
            )
            detail_prefix = "ow_wdu_d"
        rows = [
            (
                text(
                    language,
                    "wd_list_item",
                    public_id=w.public_id,
                    amount=_fmt_money(w.amount),
                    currency=w.currency.value,
                    status=w.status.value,
                ),
                f"{detail_prefix}:{w.id}",
            )
            for w in items
        ]
        keyboard = kb.list_keyboard(
            language,
            item_callbacks=rows,
            page_prefix=f"ow_{kind}",
            page=page,
            total_items=total,
            back="ow_wd",
        )
        return TelegramReply(text(language, "btn_withdrawals"), keyboard)

    async def _owner_withdrawal_detail(self, language: str, kind: str, wid) -> TelegramReply:  # noqa: ANN001
        if wid is None:
            return TelegramReply(
                text(language, "error_generic"), kb.with_nav(language, [], back="home")
            )
        if kind == "wdm":
            w = await self._merchant_withdrawal_service().get_for_owner(wid)
        elif kind == "wdu":
            w = await self._user_withdrawal_service().get_for_owner(wid)
        else:
            w = await self._team_lead_withdrawal_service().get_for_owner(wid)
        actions = []
        if w.status == WithdrawalStatus.PENDING:
            actions.append(
                [
                    kb.button(text(language, "btn_approve"), f"a:{kind}:{w.id}:appr"),
                    kb.button(text(language, "btn_reject"), f"a:{kind}:{w.id}:rej"),
                ]
            )
        elif w.status == WithdrawalStatus.APPROVED and kind in {"wdu", "tlw"}:
            actions.append([kb.button(text(language, "btn_mark_paid"), f"a:{kind}:{w.id}:paid")])
        back = "ow_wd" if kind in {"wdm", "wdu"} else "home"
        body = text(
            language,
            "wd_card",
            public_id=w.public_id,
            amount=_fmt_money(w.amount),
            currency=w.currency.value,
            status=w.status.value,
            dest_type=text(language, _DEST_LABEL_KEY[w.destination_type]),
            destination=w.destination,
            created=_fmt_dt(w.created_at),
            comment=w.comment or "-",
        )
        return TelegramReply(body, kb.with_nav(language, actions, back=back))

    async def _owner_withdrawal_action(self, data: str, account, language: str) -> TelegramReply:  # noqa: ANN001
        parts = data.split(":")
        step, kind, wid_raw, verb = parts[0], parts[1], parts[2], parts[3]
        wid = _parse_uuid(wid_raw)
        if wid is None or kind not in {"wdm", "wdu", "tlw"} or verb not in {"appr", "rej", "paid"}:
            return TelegramReply(
                text(language, "error_generic"), kb.home_menu(language, account.role)
            )
        detail_prefix = {"wdm": "ow_wdm_d", "wdu": "ow_wdu_d", "tlw": "ow_tlw_d"}[kind]
        if step == "a":
            confirm_key = {
                "appr": "confirm_approve_withdrawal",
                "rej": "confirm_reject_withdrawal",
                "paid": "confirm_mark_paid_withdrawal",
            }[verb]
            return TelegramReply(
                text(language, confirm_key),
                kb.confirm_keyboard(language, f"g:{kind}:{wid}:{verb}", f"{detail_prefix}:{wid}"),
            )

        service = {
            "wdm": self._merchant_withdrawal_service(),
            "wdu": self._user_withdrawal_service(),
            "tlw": self._team_lead_withdrawal_service(),
        }[kind]
        try:
            if verb == "appr":
                await service.approve_by_owner(account.id, wid)
            elif verb == "rej":
                await service.reject_by_owner(account.id, wid)
            else:
                await service.mark_paid_by_owner(account.id, wid)
        except (
            InvalidWithdrawalTransitionError,
            TLInvalidTransitionError,
            InsufficientBalanceError,
        ) as exc:
            return TelegramReply(
                f"{text(language, 'error_generic')}\n{exc}",
                kb.with_nav(language, [], back=f"{detail_prefix}:{wid}"),
            )
        verb_name = {"appr": "approve", "rej": "reject", "paid": "mark_paid"}[verb]
        await self._audit_log(
            action=f"{_WD_KIND_AUDIT_PREFIX[kind]}.{verb_name}", entity_id=str(wid), actor=account
        )
        return await self._owner_withdrawal_detail(language, kind, wid)

    # ------------------------------------------------------------------
    # USER screens
    # ------------------------------------------------------------------

    async def _dispatch_user(self, data: str, tg_user_id: int, account, language: str):  # noqa: ANN001, ANN201
        if data == "u_bal":
            wallet = await self._wallet_service().get_wallet_for_account(account.id)
            return TelegramReply(
                text(language, "balance", available=_fmt_money(wallet.available_balance)),
                kb.with_nav(language, [], back="home"),
            )
        if data.startswith("u_deals:"):
            page = int(data.split(":")[1])
            items = await DealRepository(self.session).list_for_user(
                account.id, status=None, limit=kb.PAGE_SIZE, offset=(page - 1) * kb.PAGE_SIZE
            )
            total = await DealRepository(self.session).count_for_user(account.id, status=None)
            rows = [
                (
                    text(
                        language,
                        "deal_list_item",
                        public_id=d.public_id,
                        amount_tjs=_fmt_money(d.amount_tjs),
                        status=d.status.value,
                    ),
                    f"u_deal_d:{d.id}",
                )
                for d in items
            ]
            keyboard = kb.list_keyboard(
                language,
                item_callbacks=rows,
                page_prefix="u_deals",
                page=page,
                total_items=total,
                back="home",
            )
            return TelegramReply(text(language, "btn_deals"), keyboard)
        if data.startswith("u_deal_d:"):
            did = _parse_uuid(data.split(":")[1])
            d = await DealRepository(self.session).get_by_id(did) if did else None
            if d is None or d.user_id != account.id:
                return TelegramReply(
                    text(language, "error_generic"), kb.with_nav(language, [], back="u_deals:1")
                )
            body = text(
                language,
                "deal_card",
                public_id=d.public_id,
                amount_tjs=_fmt_money(d.amount_tjs),
                status=d.status.value,
                created=_fmt_dt(d.created_at),
            )
            return TelegramReply(body, kb.with_nav(language, [], back="u_deals:1"))
        if data.startswith("u_wd:"):
            return await self._list_withdrawals_screen(
                account, language, page=int(data.split(":")[1]), kind="user", back="home"
            )
        if data.startswith("u_wd_d:"):
            wid = _parse_uuid(data.split(":")[1])
            if wid is None:
                return TelegramReply(
                    text(language, "error_generic"), kb.home_menu(language, account.role)
                )
            w = await self._user_withdrawal_service().get_for_user(account.id, wid)
            return self._withdrawal_detail_reply(
                w,
                language,
                back="u_wd:1",
                cancel_ask=f"u_wd_cancel_ask:{w.id}"
                if w.status == WithdrawalStatus.PENDING
                else None,
            )
        if data.startswith("u_wd_cancel_ask:"):
            wid = _parse_uuid(data.split(":")[1])
            w = await self._user_withdrawal_service().get_for_user(account.id, wid) if wid else None
            if w is None:
                return TelegramReply(
                    text(language, "error_generic"), kb.with_nav(language, [], back="u_wd:1")
                )
            return TelegramReply(
                text(language, "confirm_cancel_withdrawal", public_id=w.public_id),
                kb.confirm_keyboard(language, f"u_wd_cancel_go:{w.id}", f"u_wd_d:{w.id}"),
            )
        if data.startswith("u_wd_cancel_go:"):
            wid = _parse_uuid(data.split(":")[1])
            w = await self._user_withdrawal_service().cancel_by_user(account.id, wid)
            return TelegramReply(
                text(language, "withdrawal_cancelled", public_id=w.public_id),
                kb.with_nav(language, [], back="u_wd:1"),
            )
        if data == "u_wd_new":
            await conversation_state.set_pending(tg_user_id, {"flow": "wd_amount", "kind": "user"})
            return TelegramReply(
                text(language, "prompt_withdrawal_amount"), kb.flow_cancel_keyboard(language)
            )
        return _UNHANDLED

    # ------------------------------------------------------------------
    # MERCHANT screens
    # ------------------------------------------------------------------

    async def _dispatch_merchant(self, data: str, tg_user_id: int, account, language: str):  # noqa: ANN001, ANN201, C901
        if data == "m_bal":
            wallet = await self._wallet_service().get_merchant_wallet_for_account(account.id)
            return TelegramReply(
                text(language, "balance", available=_fmt_money(wallet.available_balance)),
                kb.with_nav(language, [], back="home"),
            )
        if data.startswith("m_inv:"):
            page = int(data.split(":")[1])
            items, total = await self._invoice_service().list_for_merchant(
                account.id, status=None, limit=kb.PAGE_SIZE, offset=(page - 1) * kb.PAGE_SIZE
            )
            rows = [
                (
                    text(
                        language,
                        "invoice_list_item",
                        public_id=i.public_id,
                        amount=_fmt_money(i.amount),
                        status=i.status.value,
                    ),
                    f"m_inv_d:{i.id}",
                )
                for i in items
            ]
            extra = [[kb.button(text(language, "btn_create_invoice"), "m_inv_new")]]
            keyboard = kb.list_keyboard(
                language,
                item_callbacks=rows,
                page_prefix="m_inv",
                page=page,
                total_items=total,
                back="home",
                extra_rows=extra,
            )
            return TelegramReply(text(language, "btn_invoices"), keyboard)
        if data.startswith("m_inv_d:"):
            iid = _parse_uuid(data.split(":")[1])
            inv = await self._invoice_service().get_for_merchant(account.id, iid) if iid else None
            if inv is None:
                return TelegramReply(
                    text(language, "error_generic"), kb.with_nav(language, [], back="m_inv:1")
                )
            body = text(
                language,
                "invoice_card",
                public_id=inv.public_id,
                amount=_fmt_money(inv.amount),
                status=inv.status.value,
                address=inv.deposit_address,
                created=_fmt_dt(inv.created_at),
                expires=_fmt_dt(inv.expires_at),
            )
            actions = []
            if inv.status == InvoiceStatus.PENDING_PAYMENT:
                actions.append(
                    [kb.button(text(language, "btn_cancel_invoice"), f"m_inv_cancel_ask:{inv.id}")]
                )
            return TelegramReply(body, kb.with_nav(language, actions, back="m_inv:1"))
        if data.startswith("m_inv_cancel_ask:"):
            iid = _parse_uuid(data.split(":")[1])
            inv = await self._invoice_service().get_for_merchant(account.id, iid) if iid else None
            if inv is None:
                return TelegramReply(
                    text(language, "error_generic"), kb.with_nav(language, [], back="m_inv:1")
                )
            return TelegramReply(
                text(language, "confirm_cancel_invoice", public_id=inv.public_id),
                kb.confirm_keyboard(language, f"m_inv_cancel_go:{inv.id}", f"m_inv_d:{inv.id}"),
            )
        if data.startswith("m_inv_cancel_go:"):
            iid = _parse_uuid(data.split(":")[1])
            try:
                inv = await self._invoice_service().cancel_invoice(account.id, iid)
            except InvoiceNotCancellableError as exc:
                return TelegramReply(
                    f"{text(language, 'error_generic')}\n{exc}",
                    kb.with_nav(language, [], back="m_inv:1"),
                )
            return TelegramReply(
                text(language, "invoice_cancelled", public_id=inv.public_id),
                kb.with_nav(language, [], back="m_inv:1"),
            )
        if data == "m_inv_new":
            await conversation_state.set_pending(tg_user_id, {"flow": "inv_amount"})
            return TelegramReply(
                text(language, "prompt_invoice_amount"), kb.invoice_flow_cancel_keyboard(language)
            )

        if data.startswith("m_deals:"):
            page = int(data.split(":")[1])
            items = await DealRepository(self.session).list_for_merchant(
                account.id, status=None, limit=kb.PAGE_SIZE, offset=(page - 1) * kb.PAGE_SIZE
            )
            total = await DealRepository(self.session).count_for_merchant(account.id, status=None)
            rows = [
                (
                    text(
                        language,
                        "deal_list_item",
                        public_id=d.public_id,
                        amount_tjs=_fmt_money(d.amount_tjs),
                        status=d.status.value,
                    ),
                    f"m_deal_d:{d.id}",
                )
                for d in items
            ]
            keyboard = kb.list_keyboard(
                language,
                item_callbacks=rows,
                page_prefix="m_deals",
                page=page,
                total_items=total,
                back="home",
            )
            return TelegramReply(text(language, "btn_deals"), keyboard)
        if data.startswith("m_deal_d:"):
            did = _parse_uuid(data.split(":")[1])
            d = await DealRepository(self.session).get_by_id(did) if did else None
            if d is None or d.merchant_id != account.id:
                return TelegramReply(
                    text(language, "error_generic"), kb.with_nav(language, [], back="m_deals:1")
                )
            body = text(
                language,
                "deal_card",
                public_id=d.public_id,
                amount_tjs=_fmt_money(d.amount_tjs),
                status=d.status.value,
                created=_fmt_dt(d.created_at),
            )
            return TelegramReply(body, kb.with_nav(language, [], back="m_deals:1"))

        if data.startswith("m_wd:"):
            return await self._list_withdrawals_screen(
                account, language, page=int(data.split(":")[1]), kind="merchant", back="home"
            )
        if data.startswith("m_wd_d:"):
            wid = _parse_uuid(data.split(":")[1])
            if wid is None:
                return TelegramReply(
                    text(language, "error_generic"), kb.home_menu(language, account.role)
                )
            w = await self._merchant_withdrawal_service().get_for_merchant(account.id, wid)
            return self._withdrawal_detail_reply(
                w,
                language,
                back="m_wd:1",
                cancel_ask=f"m_wd_cancel_ask:{w.id}"
                if w.status == WithdrawalStatus.PENDING
                else None,
            )
        if data.startswith("m_wd_cancel_ask:"):
            wid = _parse_uuid(data.split(":")[1])
            w = (
                await self._merchant_withdrawal_service().get_for_merchant(account.id, wid)
                if wid
                else None
            )
            if w is None:
                return TelegramReply(
                    text(language, "error_generic"), kb.with_nav(language, [], back="m_wd:1")
                )
            return TelegramReply(
                text(language, "confirm_cancel_withdrawal", public_id=w.public_id),
                kb.confirm_keyboard(language, f"m_wd_cancel_go:{w.id}", f"m_wd_d:{w.id}"),
            )
        if data.startswith("m_wd_cancel_go:"):
            wid = _parse_uuid(data.split(":")[1])
            w = await self._merchant_withdrawal_service().cancel_by_merchant(account.id, wid)
            return TelegramReply(
                text(language, "withdrawal_cancelled", public_id=w.public_id),
                kb.with_nav(language, [], back="m_wd:1"),
            )
        if data == "m_wd_new":
            await conversation_state.set_pending(
                tg_user_id, {"flow": "wd_amount", "kind": "merchant"}
            )
            return TelegramReply(
                text(language, "prompt_withdrawal_amount"), kb.flow_cancel_keyboard(language)
            )

        if data == "m_stats":
            stats = await self._statistics_service().for_merchant(account.id)
            body = text(
                language,
                "m_stats_body",
                inv_total=stats.invoices.total,
                inv_paid=stats.invoices.paid,
                inv_volume=_fmt_money(stats.invoices.paid_volume),
                wd_total=stats.withdrawals.total,
                wd_paid=stats.withdrawals.paid,
                wd_volume=_fmt_money(stats.withdrawals.paid_volume),
            )
            return TelegramReply(body, kb.with_nav(language, [], back="home"))

        return _UNHANDLED

    # ------------------------------------------------------------------
    # Shared list/detail helpers
    # ------------------------------------------------------------------

    async def _list_withdrawals_screen(
        self, account, language: str, *, page: int, kind: str, back: str
    ) -> TelegramReply:  # noqa: ANN001
        limit, offset = kb.PAGE_SIZE, (page - 1) * kb.PAGE_SIZE
        if kind == "tl":
            items, total = await self._team_lead_withdrawal_service().list_for_team_lead(
                account.id, status=None, limit=limit, offset=offset
            )
            detail_prefix, new_cb = "tl_wd_d", "tl_wd_new"
        elif kind == "user":
            items, total = await self._user_withdrawal_service().list_for_user(
                account.id, status=None, limit=limit, offset=offset
            )
            detail_prefix, new_cb = "u_wd_d", "u_wd_new"
        else:
            items, total = await self._merchant_withdrawal_service().list_for_merchant(
                account.id, status=None, limit=limit, offset=offset
            )
            detail_prefix, new_cb = "m_wd_d", "m_wd_new"
        rows = [
            (
                text(
                    language,
                    "wd_list_item",
                    public_id=w.public_id,
                    amount=_fmt_money(w.amount),
                    currency=w.currency.value,
                    status=w.status.value,
                ),
                f"{detail_prefix}:{w.id}",
            )
            for w in items
        ]
        extra = [[kb.button(text(language, "btn_create_withdrawal"), new_cb)]]
        keyboard = kb.list_keyboard(
            language,
            item_callbacks=rows,
            page_prefix={"tl": "tl_wd", "user": "u_wd", "merchant": "m_wd"}[kind],
            page=page,
            total_items=total,
            back=back,
            extra_rows=extra,
        )
        return TelegramReply(
            text(language, "btn_my_withdrawals" if kind == "tl" else "btn_withdrawals"), keyboard
        )

    def _withdrawal_detail_reply(
        self, w, language: str, *, back: str, cancel_ask: str | None
    ) -> TelegramReply:  # noqa: ANN001
        body = text(
            language,
            "wd_card",
            public_id=w.public_id,
            amount=_fmt_money(w.amount),
            currency=w.currency.value,
            status=w.status.value,
            dest_type=text(language, _DEST_LABEL_KEY[w.destination_type]),
            destination=w.destination,
            created=_fmt_dt(w.created_at),
            comment=w.comment or "-",
        )
        actions = (
            [[kb.button(text(language, "btn_cancel_withdrawal"), cancel_ask)]] if cancel_ask else []
        )
        return TelegramReply(body, kb.with_nav(language, actions, back=back))

    # ------------------------------------------------------------------
    # Multi-step flows (withdrawal creation, invoice creation)
    # ------------------------------------------------------------------

    async def _dispatch_flow_callback(
        self, data: str, tg_user_id: int, account, language: str
    ) -> TelegramReply:  # noqa: ANN001
        pending = await conversation_state.get_pending(tg_user_id)
        if data.startswith("wdflow:dt:"):
            if not pending or pending.get("flow") != "wd_dest_type":
                return TelegramReply(
                    text(language, "flow_expired"), kb.home_menu(language, account.role)
                )
            dest_type = data.split(":")[2]
            pending["dest_type"] = dest_type
            pending["flow"] = "wd_destination"
            await conversation_state.set_pending(tg_user_id, pending)
            return TelegramReply(
                text(language, "prompt_withdrawal_destination"), kb.flow_cancel_keyboard(language)
            )
        if data == "wdflow_cancel":
            kind = (pending or {}).get("kind", "user")
            await conversation_state.clear_pending(tg_user_id)
            back = {"tl": "tl_wd:1", "user": "u_wd:1", "merchant": "m_wd:1"}.get(kind, "home")
            return TelegramReply(
                text(language, "action_done"), kb.with_nav(language, [], back=back)
            )
        if data == "wdflow_go":
            return await self._create_withdrawal_from_pending(
                pending, tg_user_id, account, language
            )
        if data == "invflow_cancel":
            await conversation_state.clear_pending(tg_user_id)
            return TelegramReply(
                text(language, "action_done"), kb.with_nav(language, [], back="m_inv:1")
            )
        if data == "invflow_go":
            return await self._create_invoice_from_pending(pending, tg_user_id, account, language)
        return TelegramReply(text(language, "flow_expired"), kb.home_menu(language, account.role))

    async def _handle_flow_text(
        self, pending: dict, tg_user_id: int, account, language: str, raw_text: str
    ) -> TelegramReply:  # noqa: ANN001
        flow = pending.get("flow")
        if flow == "wd_amount":
            amount = _parse_amount(raw_text)
            if amount is None:
                return TelegramReply(
                    text(language, "invalid_amount"), kb.flow_cancel_keyboard(language)
                )
            pending["amount"] = str(amount)
            pending["flow"] = "wd_dest_type"
            await conversation_state.set_pending(tg_user_id, pending)
            return TelegramReply(
                text(language, "prompt_withdrawal_dest_type"),
                kb.destination_type_keyboard(language, back="wdflow_cancel"),
            )
        if flow == "wd_destination":
            destination = raw_text.strip()
            if len(destination) < 3 or len(destination) > 255:
                return TelegramReply(
                    text(language, "invalid_destination"), kb.flow_cancel_keyboard(language)
                )
            pending["destination"] = destination
            pending["flow"] = "wd_confirm"
            await conversation_state.set_pending(tg_user_id, pending)
            dest_label = text(
                language, _DEST_LABEL_KEY[WithdrawalDestinationType(pending["dest_type"])]
            )
            body = text(
                language,
                "confirm_create_withdrawal",
                amount=pending["amount"],
                dest_type=dest_label,
                destination=destination,
            )
            return TelegramReply(body, kb.confirm_keyboard(language, "wdflow_go", "wdflow_cancel"))
        if flow == "inv_amount":
            amount = _parse_amount(raw_text)
            if amount is None:
                return TelegramReply(
                    text(language, "invalid_amount"), kb.invoice_flow_cancel_keyboard(language)
                )
            pending["amount"] = str(amount)
            pending["flow"] = "inv_desc"
            await conversation_state.set_pending(tg_user_id, pending)
            return TelegramReply(
                text(language, "prompt_invoice_description"),
                kb.invoice_flow_cancel_keyboard(language),
            )
        if flow == "inv_desc":
            description = None if raw_text.strip() == "-" else raw_text.strip()[:500]
            pending["description"] = description or ""
            pending["flow"] = "inv_confirm"
            await conversation_state.set_pending(tg_user_id, pending)
            body = text(
                language,
                "confirm_create_invoice",
                amount=pending["amount"],
                description=pending["description"] or "-",
            )
            return TelegramReply(
                body, kb.confirm_keyboard(language, "invflow_go", "invflow_cancel")
            )
        await conversation_state.clear_pending(tg_user_id)
        return TelegramReply(text(language, "flow_expired"), kb.home_menu(language, account.role))

    async def _create_withdrawal_from_pending(
        self, pending: dict | None, tg_user_id: int, account, language: str
    ) -> TelegramReply:  # noqa: ANN001
        if not pending or pending.get("flow") != "wd_confirm":
            return TelegramReply(
                text(language, "flow_expired"), kb.home_menu(language, account.role)
            )
        kind = pending.get("kind")
        amount = _parse_amount(pending.get("amount", ""))
        dest_type = WithdrawalDestinationType(pending["dest_type"])
        destination = pending["destination"]
        await conversation_state.clear_pending(tg_user_id)
        back = {"tl": "tl_wd:1", "user": "u_wd:1", "merchant": "m_wd:1"}.get(kind, "home")
        try:
            if kind == "tl" and account.role == UserRole.TEAM_LEAD:
                w = await self._team_lead_withdrawal_service().create_withdrawal(
                    account, amount=amount, destination_type=dest_type, destination=destination
                )
            elif kind == "user" and account.role == UserRole.USER:
                w = await self._user_withdrawal_service(for_creation=True).create_withdrawal(
                    account, amount=amount, destination_type=dest_type, destination=destination
                )
            elif kind == "merchant" and account.role == UserRole.MERCHANT:
                w = await self._merchant_withdrawal_service(for_creation=True).create_withdrawal(
                    account, amount=amount, destination_type=dest_type, destination=destination
                )
            else:
                return TelegramReply(
                    text(language, "error_generic"), kb.home_menu(language, account.role)
                )
        except (
            WithdrawalCreationNotAllowedError,
            InvalidDestinationError,
            TLWithdrawalCreationNotAllowedError,
            TLInvalidDestinationError,
            InsufficientBalanceError,
            WalletNotFoundError,
        ) as exc:
            return TelegramReply(
                f"{text(language, 'error_generic')}\n{exc}", kb.with_nav(language, [], back=back)
            )
        return TelegramReply(
            text(language, "withdrawal_created", public_id=w.public_id, status=w.status.value),
            kb.with_nav(language, [], back=back),
        )

    async def _create_invoice_from_pending(
        self, pending: dict | None, tg_user_id: int, account, language: str
    ) -> TelegramReply:  # noqa: ANN001
        if not pending or pending.get("flow") != "inv_confirm":
            return TelegramReply(
                text(language, "flow_expired"), kb.home_menu(language, account.role)
            )
        amount = _parse_amount(pending.get("amount", ""))
        description = pending.get("description") or None
        await conversation_state.clear_pending(tg_user_id)
        try:
            invoice = await self._invoice_service().create_invoice(
                account, amount=amount, description=description, external_reference=None
            )
        except InvoiceNotAllowedError as exc:
            return TelegramReply(
                f"{text(language, 'error_generic')}\n{exc}",
                kb.with_nav(language, [], back="m_inv:1"),
            )
        return TelegramReply(
            text(language, "invoice_created", public_id=invoice.public_id),
            kb.with_nav(language, [], back="m_inv:1"),
        )


_UNHANDLED = object()


def _parse_uuid(raw: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(raw)
    except (ValueError, AttributeError):
        return None


def _parse_amount(raw: str) -> Decimal | None:
    try:
        value = Decimal(raw.strip().replace(",", "."))
    except (InvalidOperation, AttributeError):
        return None
    if not value.is_finite() or value <= 0:
        return None
    return value
