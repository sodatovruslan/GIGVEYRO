import uuid
from datetime import datetime
from decimal import Decimal

from app.enums.account import UserRole
from app.enums.wallet import BalanceBucket, Currency, LedgerEntryType
from app.models.account import Account
from app.models.ledger import LedgerEntry
from app.models.wallet import UserWallet
from app.repositories.account import AccountRepository
from app.repositories.ledger import LedgerRepository
from app.repositories.wallet import WalletRepository


class WalletNotFoundError(Exception):
    """No wallet is reachable for the given account - covers a missing
    account, a non-USER account, and a USER account without a wallet row
    yet. Collapsed into one safe error so this nested resource never
    reveals which of those is actually true."""


class InactiveAccountError(Exception):
    """Raised when a financial mutation targets a blocked account."""


class InvalidAmountError(Exception):
    """Raised when an amount fails a business-level sanity check (defense
    in depth alongside Pydantic schema validation)."""


class InsufficientBalanceError(Exception):
    """Raised when a debit would drive a balance bucket below zero."""


class WalletService:
    def __init__(
        self,
        wallet_repository: WalletRepository,
        ledger_repository: LedgerRepository,
        account_repository: AccountRepository,
    ):
        self._wallets = wallet_repository
        self._ledger = ledger_repository
        self._accounts = account_repository

    async def create_wallet_for_user(self, account: Account) -> UserWallet:
        wallet = UserWallet(account_id=account.id, currency=Currency.USDT)
        return await self._wallets.create(wallet)

    async def get_wallet_for_account(self, account_id: uuid.UUID) -> UserWallet:
        account = await self._accounts.get_by_id(account_id)
        if account is None or account.role != UserRole.USER:
            raise WalletNotFoundError()

        wallet = await self._wallets.get_by_account_id(account_id)
        if wallet is None:
            raise WalletNotFoundError()
        return wallet

    async def get_ledger_for_account(
        self,
        account_id: uuid.UUID,
        *,
        entry_type: LedgerEntryType | None,
        date_from: datetime | None,
        date_to: datetime | None,
        limit: int,
        offset: int,
    ) -> tuple[list[LedgerEntry], int]:
        await self.get_wallet_for_account(account_id)  # same visibility rule as the wallet itself

        items = await self._ledger.list_for_account(
            account_id=account_id,
            entry_type=entry_type,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )
        total = await self._ledger.count_for_account(
            account_id=account_id, entry_type=entry_type, date_from=date_from, date_to=date_to
        )
        return items, total

    async def allocate(
        self,
        *,
        actor: Account,
        target_account_id: uuid.UUID,
        amount: Decimal,
        description: str | None,
        idempotency_key: str | None,
    ) -> LedgerEntry:
        return await self._apply_bucket_change(
            actor=actor,
            target_account_id=target_account_id,
            bucket=BalanceBucket.AVAILABLE,
            entry_type=LedgerEntryType.OWNER_ALLOCATION,
            amount=amount,
            require_positive=True,
            description=description,
            idempotency_key=idempotency_key,
        )

    async def adjust_insurance(
        self,
        *,
        actor: Account,
        target_account_id: uuid.UUID,
        amount: Decimal,
        description: str | None,
        idempotency_key: str | None,
    ) -> LedgerEntry:
        return await self._apply_bucket_change(
            actor=actor,
            target_account_id=target_account_id,
            bucket=BalanceBucket.INSURANCE,
            entry_type=LedgerEntryType.INSURANCE_ADJUSTMENT,
            amount=amount,
            require_positive=False,
            description=description,
            idempotency_key=idempotency_key,
        )

    async def manual_adjust(
        self,
        *,
        actor: Account,
        target_account_id: uuid.UUID,
        amount: Decimal,
        reason: str,
        idempotency_key: str | None,
    ) -> LedgerEntry:
        return await self._apply_bucket_change(
            actor=actor,
            target_account_id=target_account_id,
            bucket=BalanceBucket.AVAILABLE,
            entry_type=LedgerEntryType.MANUAL_ADJUSTMENT,
            amount=amount,
            require_positive=False,
            description=reason,
            idempotency_key=idempotency_key,
        )

    async def _apply_bucket_change(
        self,
        *,
        actor: Account,
        target_account_id: uuid.UUID,
        bucket: BalanceBucket,
        entry_type: LedgerEntryType,
        amount: Decimal,
        require_positive: bool,
        description: str | None,
        idempotency_key: str | None,
    ) -> LedgerEntry:
        if not amount.is_finite() or amount == 0:
            raise InvalidAmountError("amount must be a non-zero, finite number")
        if require_positive and amount <= 0:
            raise InvalidAmountError("amount must be greater than zero")

        target = await self._accounts.get_by_id(target_account_id)
        if target is None or target.role != UserRole.USER:
            raise WalletNotFoundError()
        if not target.is_active:
            raise InactiveAccountError("cannot modify the wallet of an inactive account")

        # Row-locked for the remainder of this transaction so a concurrent
        # mutation on the same wallet has to wait instead of racing us.
        wallet = await self._wallets.get_by_account_id_for_update(target_account_id)
        if wallet is None:
            raise WalletNotFoundError()

        if idempotency_key is not None:
            existing = await self._ledger.get_by_wallet_and_idempotency_key(
                wallet.id, idempotency_key
            )
            if existing is not None:
                return existing

        available_before = wallet.available_balance
        insurance_before = wallet.insurance_balance
        frozen_before = wallet.frozen_balance

        if bucket == BalanceBucket.AVAILABLE:
            new_value = available_before + amount
        else:
            new_value = insurance_before + amount

        if new_value < 0:
            raise InsufficientBalanceError(f"{bucket.value} balance cannot go below zero")

        if bucket == BalanceBucket.AVAILABLE:
            wallet.available_balance = new_value
        else:
            wallet.insurance_balance = new_value

        await self._wallets.save(wallet)

        entry = LedgerEntry(
            wallet_id=wallet.id,
            account_id=target.id,
            type=entry_type,
            balance_bucket=bucket,
            currency=wallet.currency,
            amount=amount,
            available_before=available_before,
            available_after=wallet.available_balance,
            insurance_before=insurance_before,
            insurance_after=wallet.insurance_balance,
            frozen_before=frozen_before,
            frozen_after=wallet.frozen_balance,
            description=description,
            idempotency_key=idempotency_key,
            created_by_account_id=actor.id,
        )
        return await self._ledger.create(entry)
