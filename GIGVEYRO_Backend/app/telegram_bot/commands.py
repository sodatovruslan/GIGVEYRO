from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.enums.account import UserRole
from app.enums.appeal import AppealStatus
from app.enums.deal import DealStatus
from app.enums.payout import PayoutStatus
from app.enums.withdrawal import WithdrawalStatus
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
from app.repositories.notification import NotificationRepository
from app.repositories.telegram import TelegramLinkRepository
from app.services.notification_messages import render_notification_message
from app.services.telegram import TelegramLinkError, TelegramService
from app.telegram_bot.i18n import (
    SUPPORTED_LANGUAGES,
    normalize_language,
    notification_label,
    text,
)


class TelegramCommandService:
    """Strict allowlist of non-financial Telegram commands."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = TelegramLinkRepository(session)
        self.telegram = TelegramService(self.repo)
        self.notifications = NotificationRepository(session)
        self.limiter = RedisRateLimiter()

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
        safe_command = command if command in {
            "/start", "/help", "/status", "/notifications", "/settings", "/language",
            "/unlink", "/risk", "/treasury", "/payouts", "/withdrawals", "/deals",
            "/balance",
        } else "unknown"
        record_telegram_command(safe_command, "received")
        if command == "/start":
            if not argument:
                return text(fallback_language, "welcome")
            try:
                result = await self.telegram.consume_link_token(
                    raw_token=argument,
                    telegram_user_id=telegram_user_id,
                    chat_id=chat_id,
                    username=username,
                    first_name=first_name,
                    telegram_language=telegram_language,
                )
                return text(result.language, "linked")
            except TelegramLinkError:
                return text(fallback_language, "invalid_link")

        connection = await self.repo.get_by_telegram_user_id(
            telegram_user_id, include_account=True
        )
        if connection is None or connection.chat_id != chat_id:
            return text(fallback_language, "unlinked")
        account = connection.account
        language = connection.language
        if not account.is_active:
            return text(language, "blocked")
        connection.last_seen_at = datetime.now(UTC)

        if command == "/help":
            return self._help(language, account.role)
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
            UserRole.OWNER: "/risk /treasury /payouts /withdrawals /deals",
            UserRole.MERCHANT: "/balance /deals /withdrawals",
            UserRole.USER: "/balance /deals",
        }[role]
        return f"{base}\n{extra}"

    async def _latest_notifications(self, account_id, language: str) -> str:  # noqa: ANN001
        rows = (
            await self.session.execute(
                select(Notification)
                .where(Notification.account_id == account_id)
                .order_by(Notification.created_at.desc())
                .limit(5)
            )
        ).scalars().all()
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
