import uuid
from datetime import datetime
from decimal import Decimal

from app.enums.account import UserRole
from app.enums.wallet import BalanceBucket, Currency, LedgerEntryType
from app.models.account import Account
from app.models.ledger import LedgerEntry
from app.models.merchant_wallet import MerchantWallet
from app.models.wallet import UserWallet
from app.repositories.account import AccountRepository
from app.repositories.ledger import LedgerRepository
from app.repositories.merchant_wallet import MerchantWalletRepository
from app.repositories.wallet import WalletRepository


class WalletNotFoundError(Exception):
    """No wallet is reachable for the given account."""


class InactiveAccountError(Exception):
    """Raised when a financial mutation targets a blocked account."""


class InvalidAmountError(Exception):
    """Raised when an amount fails a business-level sanity check."""


class InsufficientBalanceError(Exception):
    """Raised when a debit would drive a balance bucket below zero."""


class WalletService:
    def __init__(
        self,
        wallet_repository: WalletRepository,
        ledger_repository: LedgerRepository,
        account_repository: AccountRepository,
        merchant_wallet_repository: MerchantWalletRepository | None = None,
    ):
        self._wallets = wallet_repository
        self._ledger = ledger_repository
        self._accounts = account_repository
        self._merchant_wallets = merchant_wallet_repository or MerchantWalletRepository(
            wallet_repository._session
        )

    async def create_wallet_for_user(self, account: Account) -> UserWallet:
        wallet = UserWallet(account_id=account.id, currency=Currency.USDT)
        return await self._wallets.create(wallet)

    async def create_wallet_for_merchant(self, account: Account) -> MerchantWallet:
        wallet = MerchantWallet(account_id=account.id, currency=Currency.USDT)
        return await self._merchant_wallets.create(wallet)

    async def get_wallet_for_account(self, account_id: uuid.UUID) -> UserWallet:
        account = await self._accounts.get_by_id(account_id)
        if account is None or account.role != UserRole.USER:
            raise WalletNotFoundError()

        wallet = await self._wallets.get_by_account_id(account_id)
        if wallet is None:
            raise WalletNotFoundError()
        return wallet

    async def get_merchant_wallet_for_account(self, account_id: uuid.UUID) -> MerchantWallet:
        account = await self._accounts.get_by_id(account_id)
        if account is None or account.role != UserRole.MERCHANT:
            raise WalletNotFoundError()

        wallet = await self._merchant_wallets.get_by_account_id(account_id)
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
        account = await self._accounts.get_by_id(account_id)
        if account is None or account.role not in (UserRole.USER, UserRole.MERCHANT):
            raise WalletNotFoundError()

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

    async def freeze_for_deal(
        self, *, account_id: uuid.UUID, amount: Decimal, deal_id: uuid.UUID
    ) -> LedgerEntry:
        if not amount.is_finite() or amount <= 0:
            raise InvalidAmountError("amount must be a positive, finite number")

        existing = await self._ledger.get_by_reference(
            reference_type="deal", reference_id=deal_id, entry_type=LedgerEntryType.DEAL_FREEZE
        )
        if existing is not None:
            return existing

        wallet = await self._wallets.get_by_account_id_for_update(account_id)
        if wallet is None:
            raise WalletNotFoundError()

        available_before = wallet.available_balance
        insurance_before = wallet.insurance_balance
        frozen_before = wallet.frozen_balance

        if available_before < amount:
            raise InsufficientBalanceError("available balance cannot cover this deal")

        wallet.available_balance = available_before - amount
        wallet.frozen_balance = frozen_before + amount
        await self._wallets.save(wallet)

        entry = LedgerEntry(
            wallet_id=wallet.id,
            account_id=account_id,
            type=LedgerEntryType.DEAL_FREEZE,
            balance_bucket=BalanceBucket.FROZEN,
            currency=wallet.currency,
            amount=amount,
            available_before=available_before,
            available_after=wallet.available_balance,
            insurance_before=insurance_before,
            insurance_after=wallet.insurance_balance,
            frozen_before=frozen_before,
            frozen_after=wallet.frozen_balance,
            reference_type="deal",
            reference_id=deal_id,
            description="Freeze for accepted deal",
            created_by_account_id=account_id,
        )
        return await self._ledger.create(entry)

    async def release_for_deal(
        self, *, user_account_id: uuid.UUID, amount: Decimal, deal_id: uuid.UUID
    ) -> LedgerEntry:
        """Unfreezes user funds for a cancelled/released deal."""
        if not amount.is_finite() or amount <= 0:
            raise InvalidAmountError("amount must be a positive, finite number")

        existing = await self._ledger.get_by_reference(
            reference_type="deal", reference_id=deal_id, entry_type=LedgerEntryType.DEAL_RELEASE
        )
        if existing is not None:
            return existing

        wallet = await self._wallets.get_by_account_id_for_update(user_account_id)
        if wallet is None:
            raise WalletNotFoundError()

        if wallet.frozen_balance < amount:
            raise InsufficientBalanceError("frozen balance is insufficient to release deal funds")

        available_before = wallet.available_balance
        insurance_before = wallet.insurance_balance
        frozen_before = wallet.frozen_balance

        wallet.frozen_balance = frozen_before - amount
        wallet.available_balance = available_before + amount
        await self._wallets.save(wallet)

        entry = LedgerEntry(
            wallet_id=wallet.id,
            account_id=user_account_id,
            type=LedgerEntryType.DEAL_RELEASE,
            balance_bucket=BalanceBucket.AVAILABLE,
            currency=wallet.currency,
            amount=amount,
            available_before=available_before,
            available_after=wallet.available_balance,
            insurance_before=insurance_before,
            insurance_after=wallet.insurance_balance,
            frozen_before=frozen_before,
            frozen_after=wallet.frozen_balance,
            reference_type="deal",
            reference_id=deal_id,
            description="Release frozen funds for cancelled deal",
            created_by_account_id=user_account_id,
        )
        return await self._ledger.create(entry)

    async def settle_deal(
        self,
        *,
        user_account_id: uuid.UUID,
        merchant_account_id: uuid.UUID,
        amount: Decimal,
        deal_id: uuid.UUID,
        actor_id: uuid.UUID | None = None,
    ) -> tuple[LedgerEntry, LedgerEntry]:
        """Settles completed deal: User frozen -= amount, Merchant available += amount."""
        if not amount.is_finite() or amount <= 0:
            raise InvalidAmountError("amount must be a positive, finite number")

        user_existing = await self._ledger.get_by_reference(
            reference_type="deal", reference_id=deal_id, entry_type=LedgerEntryType.DEAL_SETTLEMENT
        )
        merchant_existing = await self._ledger.get_by_reference(
            reference_type="deal",
            reference_id=deal_id,
            entry_type=LedgerEntryType.DEAL_SETTLEMENT_CREDIT,
        )
        if user_existing is not None and merchant_existing is not None:
            return user_existing, merchant_existing

        # Lock ordering: UserWallet then MerchantWallet
        user_wallet = await self._wallets.get_by_account_id_for_update(user_account_id)
        if user_wallet is None:
            raise WalletNotFoundError()

        merchant_wallet = await self._merchant_wallets.get_by_account_id_for_update(
            merchant_account_id
        )
        if merchant_wallet is None:
            raise WalletNotFoundError()

        if user_wallet.frozen_balance < amount:
            raise InsufficientBalanceError("insufficient frozen balance for deal settlement")

        # 1. Update User wallet (frozen -= amount)
        u_avail_before = user_wallet.available_balance
        u_ins_before = user_wallet.insurance_balance
        u_froz_before = user_wallet.frozen_balance

        user_wallet.frozen_balance = u_froz_before - amount
        await self._wallets.save(user_wallet)

        user_entry = LedgerEntry(
            wallet_id=user_wallet.id,
            account_id=user_account_id,
            type=LedgerEntryType.DEAL_SETTLEMENT,
            balance_bucket=BalanceBucket.FROZEN,
            currency=user_wallet.currency,
            amount=-amount,
            available_before=u_avail_before,
            available_after=user_wallet.available_balance,
            insurance_before=u_ins_before,
            insurance_after=user_wallet.insurance_balance,
            frozen_before=u_froz_before,
            frozen_after=user_wallet.frozen_balance,
            reference_type="deal",
            reference_id=deal_id,
            description="Settlement deduction from frozen balance",
            created_by_account_id=actor_id,
        )
        user_entry = await self._ledger.create(user_entry)

        # 2. Update Merchant wallet (available += amount)
        m_avail_before = merchant_wallet.available_balance
        m_held_before = merchant_wallet.held_balance

        merchant_wallet.available_balance = m_avail_before + amount
        await self._merchant_wallets.save(merchant_wallet)

        merchant_entry = LedgerEntry(
            merchant_wallet_id=merchant_wallet.id,
            account_id=merchant_account_id,
            type=LedgerEntryType.DEAL_SETTLEMENT_CREDIT,
            balance_bucket=BalanceBucket.AVAILABLE,
            currency=merchant_wallet.currency,
            amount=amount,
            available_before=m_avail_before,
            available_after=merchant_wallet.available_balance,
            insurance_before=Decimal("0"),
            insurance_after=Decimal("0"),
            frozen_before=Decimal("0"),
            frozen_after=Decimal("0"),
            held_before=m_held_before,
            held_after=merchant_wallet.held_balance,
            reference_type="deal",
            reference_id=deal_id,
            description="Settlement credit from completed deal",
            created_by_account_id=actor_id,
        )
        merchant_entry = await self._ledger.create(merchant_entry)

        return user_entry, merchant_entry

    # -- STAGE 10 WITHDRAWAL WALLET MUTATIONS ---------------------------

    async def hold_for_withdrawal(
        self, *, merchant_id: uuid.UUID, amount: Decimal, withdrawal_id: uuid.UUID
    ) -> LedgerEntry:
        if not amount.is_finite() or amount <= 0:
            raise InvalidAmountError("amount must be a positive, finite number")

        existing = await self._ledger.get_by_reference(
            reference_type="withdrawal",
            reference_id=withdrawal_id,
            entry_type=LedgerEntryType.WITHDRAWAL_HOLD,
        )
        if existing is not None:
            return existing

        merchant_wallet = await self._merchant_wallets.get_by_account_id_for_update(merchant_id)
        if merchant_wallet is None:
            raise WalletNotFoundError()

        m_avail_before = merchant_wallet.available_balance
        m_held_before = merchant_wallet.held_balance

        if m_avail_before < amount:
            raise InsufficientBalanceError("insufficient available balance for withdrawal")

        merchant_wallet.available_balance = m_avail_before - amount
        merchant_wallet.held_balance = m_held_before + amount
        await self._merchant_wallets.save(merchant_wallet)

        entry = LedgerEntry(
            merchant_wallet_id=merchant_wallet.id,
            account_id=merchant_id,
            type=LedgerEntryType.WITHDRAWAL_HOLD,
            balance_bucket=BalanceBucket.HELD,
            currency=merchant_wallet.currency,
            amount=amount,
            available_before=m_avail_before,
            available_after=merchant_wallet.available_balance,
            insurance_before=Decimal("0"),
            insurance_after=Decimal("0"),
            frozen_before=Decimal("0"),
            frozen_after=Decimal("0"),
            held_before=m_held_before,
            held_after=merchant_wallet.held_balance,
            reference_type="withdrawal",
            reference_id=withdrawal_id,
            description="Hold balance for withdrawal request",
            created_by_account_id=merchant_id,
        )
        return await self._ledger.create(entry)

    async def release_for_withdrawal(
        self,
        *,
        merchant_id: uuid.UUID,
        amount: Decimal,
        withdrawal_id: uuid.UUID,
        actor_id: uuid.UUID,
    ) -> LedgerEntry:
        if not amount.is_finite() or amount <= 0:
            raise InvalidAmountError("amount must be a positive, finite number")

        existing = await self._ledger.get_by_reference(
            reference_type="withdrawal",
            reference_id=withdrawal_id,
            entry_type=LedgerEntryType.WITHDRAWAL_RELEASE,
        )
        if existing is not None:
            return existing

        merchant_wallet = await self._merchant_wallets.get_by_account_id_for_update(merchant_id)
        if merchant_wallet is None:
            raise WalletNotFoundError()

        m_avail_before = merchant_wallet.available_balance
        m_held_before = merchant_wallet.held_balance

        if m_held_before < amount:
            raise InsufficientBalanceError("insufficient held balance to release withdrawal")

        merchant_wallet.held_balance = m_held_before - amount
        merchant_wallet.available_balance = m_avail_before + amount
        await self._merchant_wallets.save(merchant_wallet)

        entry = LedgerEntry(
            merchant_wallet_id=merchant_wallet.id,
            account_id=merchant_id,
            type=LedgerEntryType.WITHDRAWAL_RELEASE,
            balance_bucket=BalanceBucket.AVAILABLE,
            currency=merchant_wallet.currency,
            amount=amount,
            available_before=m_avail_before,
            available_after=merchant_wallet.available_balance,
            insurance_before=Decimal("0"),
            insurance_after=Decimal("0"),
            frozen_before=Decimal("0"),
            frozen_after=Decimal("0"),
            held_before=m_held_before,
            held_after=merchant_wallet.held_balance,
            reference_type="withdrawal",
            reference_id=withdrawal_id,
            description="Release held balance for rejected/cancelled withdrawal",
            created_by_account_id=actor_id,
        )
        return await self._ledger.create(entry)

    async def pay_withdrawal(
        self,
        *,
        merchant_id: uuid.UUID,
        amount: Decimal,
        withdrawal_id: uuid.UUID,
        actor_id: uuid.UUID,
    ) -> LedgerEntry:
        if not amount.is_finite() or amount <= 0:
            raise InvalidAmountError("amount must be a positive, finite number")

        existing = await self._ledger.get_by_reference(
            reference_type="withdrawal",
            reference_id=withdrawal_id,
            entry_type=LedgerEntryType.WITHDRAWAL_PAID,
        )
        if existing is not None:
            return existing

        merchant_wallet = await self._merchant_wallets.get_by_account_id_for_update(merchant_id)
        if merchant_wallet is None:
            raise WalletNotFoundError()

        m_avail_before = merchant_wallet.available_balance
        m_held_before = merchant_wallet.held_balance

        if m_held_before < amount:
            raise InsufficientBalanceError("insufficient held balance to mark paid")

        merchant_wallet.held_balance = m_held_before - amount
        await self._merchant_wallets.save(merchant_wallet)

        entry = LedgerEntry(
            merchant_wallet_id=merchant_wallet.id,
            account_id=merchant_id,
            type=LedgerEntryType.WITHDRAWAL_PAID,
            balance_bucket=BalanceBucket.HELD,
            currency=merchant_wallet.currency,
            amount=-amount,
            available_before=m_avail_before,
            available_after=merchant_wallet.available_balance,
            insurance_before=Decimal("0"),
            insurance_after=Decimal("0"),
            frozen_before=Decimal("0"),
            frozen_after=Decimal("0"),
            held_before=m_held_before,
            held_after=merchant_wallet.held_balance,
            reference_type="withdrawal",
            reference_id=withdrawal_id,
            description="Final deduction of held funds upon paid withdrawal",
            created_by_account_id=actor_id,
        )
        return await self._ledger.create(entry)

    async def credit_deposit(
        self, *, account_id: uuid.UUID, amount: Decimal, deposit_id: uuid.UUID
    ) -> LedgerEntry:
        if not amount.is_finite() or amount <= 0:
            raise InvalidAmountError("amount must be a positive, finite number")

        existing = await self._ledger.get_by_reference(
            reference_type="deposit",
            reference_id=deposit_id,
            entry_type=LedgerEntryType.DEPOSIT_CREDIT,
        )
        if existing is not None:
            return existing

        wallet = await self._wallets.get_by_account_id_for_update(account_id)
        if wallet is None:
            raise WalletNotFoundError()

        available_before = wallet.available_balance
        insurance_before = wallet.insurance_balance
        frozen_before = wallet.frozen_balance

        wallet.available_balance = available_before + amount
        await self._wallets.save(wallet)

        entry = LedgerEntry(
            wallet_id=wallet.id,
            account_id=account_id,
            type=LedgerEntryType.DEPOSIT_CREDIT,
            balance_bucket=BalanceBucket.AVAILABLE,
            currency=wallet.currency,
            amount=amount,
            available_before=available_before,
            available_after=wallet.available_balance,
            insurance_before=insurance_before,
            insurance_after=wallet.insurance_balance,
            frozen_before=frozen_before,
            frozen_after=wallet.frozen_balance,
            reference_type="deposit",
            reference_id=deposit_id,
            description="Credit for confirmed TRC20 deposit",
            created_by_account_id=None,
        )
        return await self._ledger.create(entry)

    async def credit_deposit_for_merchant(
        self, *, merchant_id: uuid.UUID, amount: Decimal, deposit_id: uuid.UUID
    ) -> LedgerEntry:
        """Same contract as credit_deposit(), but for an invoice-linked deposit
        whose account_id is a MERCHANT - credits MerchantWallet, not UserWallet."""
        if not amount.is_finite() or amount <= 0:
            raise InvalidAmountError("amount must be a positive, finite number")

        existing = await self._ledger.get_by_reference(
            reference_type="deposit",
            reference_id=deposit_id,
            entry_type=LedgerEntryType.DEPOSIT_CREDIT,
        )
        if existing is not None:
            return existing

        merchant_wallet = await self._merchant_wallets.get_by_account_id_for_update(merchant_id)
        if merchant_wallet is None:
            raise WalletNotFoundError()

        available_before = merchant_wallet.available_balance
        held_before = merchant_wallet.held_balance

        merchant_wallet.available_balance = available_before + amount
        await self._merchant_wallets.save(merchant_wallet)

        entry = LedgerEntry(
            merchant_wallet_id=merchant_wallet.id,
            account_id=merchant_id,
            type=LedgerEntryType.DEPOSIT_CREDIT,
            balance_bucket=BalanceBucket.AVAILABLE,
            currency=merchant_wallet.currency,
            amount=amount,
            available_before=available_before,
            available_after=merchant_wallet.available_balance,
            insurance_before=Decimal("0"),
            insurance_after=Decimal("0"),
            frozen_before=Decimal("0"),
            frozen_after=Decimal("0"),
            held_before=held_before,
            held_after=merchant_wallet.held_balance,
            reference_type="deposit",
            reference_id=deposit_id,
            description="Credit for confirmed TRC20 invoice deposit",
            created_by_account_id=None,
        )
        return await self._ledger.create(entry)

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
