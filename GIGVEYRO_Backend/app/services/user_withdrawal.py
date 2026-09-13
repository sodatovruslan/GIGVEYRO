import secrets
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy.exc import IntegrityError

from app.enums.account import UserRole
from app.enums.notification import NotificationMessageKey, NotificationType
from app.enums.withdrawal import WithdrawalDestinationType, WithdrawalStatus
from app.models.account import Account
from app.models.user_withdrawal import UserWithdrawal
from app.repositories.account import AccountRepository
from app.repositories.user_withdrawal import UserWithdrawalRepository
from app.services.notification import NotificationService
from app.services.realtime import RealtimeEventService
from app.services.risk import RiskGuard
from app.services.wallet import WalletService
from app.services.withdrawal import (
    InvalidDestinationError,
    InvalidWithdrawalTransitionError,
    WithdrawalCreationNotAllowedError,
    WithdrawalNotFoundError,
    transition_withdrawal,
)


def generate_user_withdrawal_public_id() -> str:
    return f"UWD-{secrets.token_hex(4).upper()}"


class UserWithdrawalService:
    def __init__(
        self,
        withdrawal_repository: UserWithdrawalRepository,
        wallet_service: WalletService,
        account_repository: AccountRepository,
        notification_service: NotificationService | None = None,
        risk_guard: RiskGuard | None = None,
        realtime_service: RealtimeEventService | None = None,
    ):
        self._withdrawals = withdrawal_repository
        self._wallet_service = wallet_service
        self._accounts = account_repository
        self._notifications = notification_service
        self._risk_guard = risk_guard
        self._realtime = realtime_service

    async def _notify_status_changed(self, withdrawal: UserWithdrawal) -> None:
        if self._notifications is None:
            return
        message_key = {
            WithdrawalStatus.CANCELLED: NotificationMessageKey.WITHDRAWAL_CANCELLED,
            WithdrawalStatus.APPROVED: NotificationMessageKey.WITHDRAWAL_APPROVED,
            WithdrawalStatus.REJECTED: NotificationMessageKey.WITHDRAWAL_REJECTED,
            WithdrawalStatus.PAID: NotificationMessageKey.WITHDRAWAL_COMPLETED,
        }[withdrawal.status]
        await self._notifications.emit_semantic_notification(
            withdrawal.user_id,
            NotificationType.WITHDRAWAL_STATUS_CHANGED,
            message_key,
            {"reference": withdrawal.public_id},
            payload={"withdrawal_id": str(withdrawal.id), "status": withdrawal.status.value},
            dedupe_key=f"user_withdrawal_status:{withdrawal.id}:{withdrawal.status.value}",
        )

    async def _realtime_notify(self, withdrawal: UserWithdrawal) -> None:
        if self._realtime is not None:
            await self._realtime.enqueue_user_withdrawal_updated(withdrawal)

    async def create_withdrawal(
        self,
        user: Account,
        *,
        amount: Decimal,
        destination_type: WithdrawalDestinationType,
        destination: str,
        comment: str | None = None,
    ) -> UserWithdrawal:
        if user.role != UserRole.USER or not user.is_active:
            raise WithdrawalCreationNotAllowedError(
                "only active USER accounts can create withdrawals"
            )

        if not amount.is_finite() or amount <= 0:
            raise WithdrawalCreationNotAllowedError("amount must be a positive, finite number")

        destination_clean = destination.strip()
        if not destination_clean:
            raise InvalidDestinationError("destination cannot be empty")

        if destination_type == WithdrawalDestinationType.USDT_TRC20_ADDRESS:
            if len(destination_clean) < 26 or len(destination_clean) > 50:
                raise InvalidDestinationError("invalid TRC20 address length")

        wallet = await self._wallet_service.get_wallet_for_account(user.id)
        if self._risk_guard is not None:
            await self._risk_guard.check_withdrawal(amount)

        last_error: IntegrityError | None = None
        for _ in range(3):
            withdrawal = UserWithdrawal(
                public_id=generate_user_withdrawal_public_id(),
                user_id=user.id,
                wallet_id=wallet.id,
                amount=amount,
                destination_type=destination_type,
                destination=destination_clean,
                status=WithdrawalStatus.PENDING,
                comment=comment,
                created_by_account_id=user.id,
            )
            try:
                withdrawal = await self._withdrawals.create(withdrawal)
                break
            except IntegrityError as exc:
                last_error = exc
        else:
            raise last_error  # pragma: no cover

        await self._wallet_service.hold_for_user_withdrawal(
            user_id=user.id, amount=amount, withdrawal_id=withdrawal.id
        )

        return withdrawal

    async def cancel_by_user(
        self, user_id: uuid.UUID, withdrawal_id: uuid.UUID
    ) -> UserWithdrawal:
        withdrawal = await self._withdrawals.get_by_id_for_update(withdrawal_id)
        if withdrawal is None or withdrawal.user_id != user_id:
            raise WithdrawalNotFoundError()

        if withdrawal.status == WithdrawalStatus.CANCELLED:
            return withdrawal

        if withdrawal.status != WithdrawalStatus.PENDING:
            raise InvalidWithdrawalTransitionError(
                f"cannot cancel withdrawal in status {withdrawal.status}"
            )

        await self._wallet_service.release_for_user_withdrawal(
            user_id=user_id,
            amount=withdrawal.amount,
            withdrawal_id=withdrawal.id,
            actor_id=user_id,
        )

        transition_withdrawal(withdrawal, WithdrawalStatus.CANCELLED, actor_id=user_id)
        saved = await self._withdrawals.save(withdrawal)
        await self._notify_status_changed(saved)
        await self._realtime_notify(saved)
        return saved

    async def get_for_user(
        self, user_id: uuid.UUID, withdrawal_id: uuid.UUID
    ) -> UserWithdrawal:
        withdrawal = await self._withdrawals.get_by_id(withdrawal_id)
        if withdrawal is None or withdrawal.user_id != user_id:
            raise WithdrawalNotFoundError()
        return withdrawal

    async def list_for_user(
        self, user_id: uuid.UUID, *, status: WithdrawalStatus | None, limit: int, offset: int
    ) -> tuple[list[UserWithdrawal], int]:
        items = await self._withdrawals.list_for_user(
            user_id, status=status, limit=limit, offset=offset
        )
        total = await self._withdrawals.count_for_user(user_id, status=status)
        return items, total

    async def approve_by_owner(
        self, owner_id: uuid.UUID, withdrawal_id: uuid.UUID, comment: str | None = None
    ) -> UserWithdrawal:
        withdrawal = await self._withdrawals.get_by_id_for_update(withdrawal_id)
        if withdrawal is None:
            raise WithdrawalNotFoundError()

        if withdrawal.status == WithdrawalStatus.APPROVED:
            return withdrawal

        if withdrawal.status != WithdrawalStatus.PENDING:
            raise InvalidWithdrawalTransitionError(
                f"cannot approve withdrawal in status {withdrawal.status}"
            )

        if comment:
            withdrawal.owner_comment = comment

        transition_withdrawal(withdrawal, WithdrawalStatus.APPROVED, actor_id=owner_id)
        saved = await self._withdrawals.save(withdrawal)
        await self._notify_status_changed(saved)
        await self._realtime_notify(saved)
        return saved

    async def reject_by_owner(
        self, owner_id: uuid.UUID, withdrawal_id: uuid.UUID, comment: str | None = None
    ) -> UserWithdrawal:
        withdrawal = await self._withdrawals.get_by_id_for_update(withdrawal_id)
        if withdrawal is None:
            raise WithdrawalNotFoundError()

        if withdrawal.status == WithdrawalStatus.REJECTED:
            return withdrawal

        if withdrawal.status != WithdrawalStatus.PENDING:
            raise InvalidWithdrawalTransitionError(
                f"cannot reject withdrawal in status {withdrawal.status}"
            )

        if comment:
            withdrawal.owner_comment = comment

        await self._wallet_service.release_for_user_withdrawal(
            user_id=withdrawal.user_id,
            amount=withdrawal.amount,
            withdrawal_id=withdrawal.id,
            actor_id=owner_id,
        )

        transition_withdrawal(withdrawal, WithdrawalStatus.REJECTED, actor_id=owner_id)
        saved = await self._withdrawals.save(withdrawal)
        await self._notify_status_changed(saved)
        await self._realtime_notify(saved)
        return saved

    async def mark_paid_by_owner(
        self, owner_id: uuid.UUID, withdrawal_id: uuid.UUID, comment: str | None = None
    ) -> UserWithdrawal:
        withdrawal = await self._withdrawals.get_by_id_for_update(withdrawal_id)
        if withdrawal is None:
            raise WithdrawalNotFoundError()

        if withdrawal.status == WithdrawalStatus.PAID:
            return withdrawal

        if withdrawal.status != WithdrawalStatus.APPROVED:
            raise InvalidWithdrawalTransitionError(
                f"cannot mark paid withdrawal in status {withdrawal.status}"
            )

        if comment:
            withdrawal.owner_comment = comment

        await self._wallet_service.pay_for_user_withdrawal(
            user_id=withdrawal.user_id,
            amount=withdrawal.amount,
            withdrawal_id=withdrawal.id,
            actor_id=owner_id,
        )

        transition_withdrawal(withdrawal, WithdrawalStatus.PAID, actor_id=owner_id)
        saved = await self._withdrawals.save(withdrawal)
        await self._notify_status_changed(saved)
        await self._realtime_notify(saved)
        return saved

    async def get_for_owner(self, withdrawal_id: uuid.UUID) -> UserWithdrawal:
        withdrawal = await self._withdrawals.get_by_id(withdrawal_id)
        if withdrawal is None:
            raise WithdrawalNotFoundError()
        return withdrawal

    async def list_for_owner(
        self,
        *,
        status: WithdrawalStatus | None,
        user_id: uuid.UUID | None,
        search: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
        limit: int,
        offset: int,
    ) -> tuple[list[UserWithdrawal], int]:
        items = await self._withdrawals.list_all(
            status=status,
            user_id=user_id,
            search=search,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )
        total = await self._withdrawals.count_all(
            status=status,
            user_id=user_id,
            search=search,
            date_from=date_from,
            date_to=date_to,
        )
        return items, total
