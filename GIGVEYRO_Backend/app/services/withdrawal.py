import secrets
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.exc import IntegrityError

from app.enums.account import UserRole
from app.enums.withdrawal import WithdrawalDestinationType, WithdrawalStatus
from app.models.account import Account
from app.models.withdrawal import MerchantWithdrawal
from app.repositories.account import AccountRepository
from app.repositories.withdrawal import WithdrawalRepository
from app.services.wallet import WalletService


class WithdrawalNotFoundError(Exception):
    """Raised when withdrawal does not exist or isn't accessible."""


class WithdrawalCreationNotAllowedError(Exception):
    """Raised when creation is attempted by non-merchant or invalid input."""


class InvalidWithdrawalTransitionError(Exception):
    """Raised when attempting an illegal withdrawal state transition."""


class InvalidDestinationError(Exception):
    """Raised when destination fails basic structural check."""


def generate_withdrawal_public_id() -> str:
    return f"WD-{secrets.token_hex(4).upper()}"


ALLOWED_TRANSITIONS: dict[WithdrawalStatus, set[WithdrawalStatus]] = {
    WithdrawalStatus.PENDING: {
        WithdrawalStatus.APPROVED,
        WithdrawalStatus.REJECTED,
        WithdrawalStatus.CANCELLED,
    },
    WithdrawalStatus.APPROVED: {
        WithdrawalStatus.PAID,
    },
    WithdrawalStatus.PAID: set(),
    WithdrawalStatus.REJECTED: set(),
    WithdrawalStatus.CANCELLED: set(),
}


def transition_withdrawal(
    withdrawal: MerchantWithdrawal, new_status: WithdrawalStatus, actor_id: uuid.UUID
) -> None:
    if new_status not in ALLOWED_TRANSITIONS.get(withdrawal.status, set()):
        raise InvalidWithdrawalTransitionError(
            f"cannot transition withdrawal from {withdrawal.status} to {new_status}"
        )
    withdrawal.status = new_status
    withdrawal.actioned_by_account_id = actor_id
    now = datetime.now(UTC)
    if new_status == WithdrawalStatus.APPROVED:
        withdrawal.approved_at = now
    elif new_status == WithdrawalStatus.REJECTED:
        withdrawal.rejected_at = now
    elif new_status == WithdrawalStatus.PAID:
        withdrawal.paid_at = now
    elif new_status == WithdrawalStatus.CANCELLED:
        withdrawal.cancelled_at = now


class WithdrawalService:
    def __init__(
        self,
        withdrawal_repository: WithdrawalRepository,
        wallet_service: WalletService,
        account_repository: AccountRepository,
    ):
        self._withdrawals = withdrawal_repository
        self._wallet_service = wallet_service
        self._accounts = account_repository

    async def create_withdrawal(
        self,
        merchant: Account,
        *,
        amount: Decimal,
        destination_type: WithdrawalDestinationType,
        destination: str,
        comment: str | None = None,
    ) -> MerchantWithdrawal:
        if merchant.role != UserRole.MERCHANT or not merchant.is_active:
            raise WithdrawalCreationNotAllowedError("only active MERCHANT accounts can create withdrawals")

        if not amount.is_finite() or amount <= 0:
            raise WithdrawalCreationNotAllowedError("amount must be a positive, finite number")

        destination_clean = destination.strip()
        if not destination_clean:
            raise InvalidDestinationError("destination cannot be empty")

        if destination_type == WithdrawalDestinationType.USDT_TRC20_ADDRESS:
            if len(destination_clean) < 26 or len(destination_clean) > 50:
                raise InvalidDestinationError("invalid TRC20 address length")

        merchant_wallet = await self._wallet_service.get_merchant_wallet_for_account(merchant.id)

        last_error: IntegrityError | None = None
        for _ in range(3):
            withdrawal = MerchantWithdrawal(
                public_id=generate_withdrawal_public_id(),
                merchant_id=merchant.id,
                merchant_wallet_id=merchant_wallet.id,
                amount=amount,
                destination_type=destination_type,
                destination=destination_clean,
                status=WithdrawalStatus.PENDING,
                comment=comment,
                created_by_account_id=merchant.id,
            )
            try:
                withdrawal = await self._withdrawals.create(withdrawal)
                break
            except IntegrityError as exc:
                last_error = exc
        else:
            raise last_error  # pragma: no cover

        await self._wallet_service.hold_for_withdrawal(
            merchant_id=merchant.id, amount=amount, withdrawal_id=withdrawal.id
        )

        return withdrawal

    async def cancel_by_merchant(
        self, merchant_id: uuid.UUID, withdrawal_id: uuid.UUID
    ) -> MerchantWithdrawal:
        withdrawal = await self._withdrawals.get_by_id_for_update(withdrawal_id)
        if withdrawal is None or withdrawal.merchant_id != merchant_id:
            raise WithdrawalNotFoundError()

        if withdrawal.status == WithdrawalStatus.CANCELLED:
            return withdrawal

        if withdrawal.status != WithdrawalStatus.PENDING:
            raise InvalidWithdrawalTransitionError(
                f"cannot cancel withdrawal in status {withdrawal.status}"
            )

        await self._wallet_service.release_for_withdrawal(
            merchant_id=merchant_id,
            amount=withdrawal.amount,
            withdrawal_id=withdrawal.id,
            actor_id=merchant_id,
        )

        transition_withdrawal(withdrawal, WithdrawalStatus.CANCELLED, actor_id=merchant_id)
        return await self._withdrawals.save(withdrawal)

    async def get_for_merchant(
        self, merchant_id: uuid.UUID, withdrawal_id: uuid.UUID
    ) -> MerchantWithdrawal:
        withdrawal = await self._withdrawals.get_by_id(withdrawal_id)
        if withdrawal is None or withdrawal.merchant_id != merchant_id:
            raise WithdrawalNotFoundError()
        return withdrawal

    async def list_for_merchant(
        self, merchant_id: uuid.UUID, *, status: WithdrawalStatus | None, limit: int, offset: int
    ) -> tuple[list[MerchantWithdrawal], int]:
        items = await self._withdrawals.list_for_merchant(
            merchant_id, status=status, limit=limit, offset=offset
        )
        total = await self._withdrawals.count_for_merchant(merchant_id, status=status)
        return items, total

    # -- OWNER ACTIONS ----------------------------------------------------

    async def approve_by_owner(
        self, owner_id: uuid.UUID, withdrawal_id: uuid.UUID, comment: str | None = None
    ) -> MerchantWithdrawal:
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
        return await self._withdrawals.save(withdrawal)

    async def reject_by_owner(
        self, owner_id: uuid.UUID, withdrawal_id: uuid.UUID, comment: str | None = None
    ) -> MerchantWithdrawal:
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

        await self._wallet_service.release_for_withdrawal(
            merchant_id=withdrawal.merchant_id,
            amount=withdrawal.amount,
            withdrawal_id=withdrawal.id,
            actor_id=owner_id,
        )

        transition_withdrawal(withdrawal, WithdrawalStatus.REJECTED, actor_id=owner_id)
        return await self._withdrawals.save(withdrawal)

    async def mark_paid_by_owner(
        self, owner_id: uuid.UUID, withdrawal_id: uuid.UUID, comment: str | None = None
    ) -> MerchantWithdrawal:
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

        await self._wallet_service.pay_withdrawal(
            merchant_id=withdrawal.merchant_id,
            amount=withdrawal.amount,
            withdrawal_id=withdrawal.id,
            actor_id=owner_id,
        )

        transition_withdrawal(withdrawal, WithdrawalStatus.PAID, actor_id=owner_id)
        return await self._withdrawals.save(withdrawal)

    async def get_for_owner(self, withdrawal_id: uuid.UUID) -> MerchantWithdrawal:
        withdrawal = await self._withdrawals.get_by_id(withdrawal_id)
        if withdrawal is None:
            raise WithdrawalNotFoundError()
        return withdrawal

    async def list_for_owner(
        self,
        *,
        status: WithdrawalStatus | None,
        merchant_id: uuid.UUID | None,
        search: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
        limit: int,
        offset: int,
    ) -> tuple[list[MerchantWithdrawal], int]:
        items = await self._withdrawals.list_all(
            status=status,
            merchant_id=merchant_id,
            search=search,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )
        total = await self._withdrawals.count_all(
            status=status,
            merchant_id=merchant_id,
            search=search,
            date_from=date_from,
            date_to=date_to,
        )
        return items, total
