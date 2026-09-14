import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy.exc import IntegrityError

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
        if account is None or account.role not in (UserRole.USER, UserRole.TEAM_LEAD):
            raise WalletNotFoundError()

        wallet = await self._wallets.get_by_account_id(account_id)
        if wallet is None:
            raise WalletNotFoundError()
        return wallet

    async def get_wallet_for_account_for_update(self, account_id: uuid.UUID) -> UserWallet:
        """Same as get_wallet_for_account, but row-locked. Callers that will
        immediately insert a row referencing this wallet (an FK check takes
        its own ShareLock) and then separately hold/mutate it must acquire
        this lock FIRST - taking the weaker FK ShareLock before the
        FOR UPDATE lock is exactly the classic ordering that deadlocks two
        concurrent callers against each other (each holds the other's
        needed lock). See TeamLeadWithdrawalService.create_withdrawal."""
        account = await self._accounts.get_by_id(account_id)
        if account is None or account.role not in (UserRole.USER, UserRole.TEAM_LEAD):
            raise WalletNotFoundError()

        wallet = await self._wallets.get_by_account_id_for_update(account_id)
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
        if account is None or account.role not in (
            UserRole.USER,
            UserRole.MERCHANT,
            UserRole.TEAM_LEAD,
        ):
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
        idempotency_key: str,
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
        idempotency_key: str,
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
        merchant_amount: Decimal,
        user_profit_amount: Decimal,
        deal_id: uuid.UUID,
        actor_id: uuid.UUID | None = None,
    ) -> tuple[LedgerEntry, LedgerEntry, LedgerEntry | None]:
        """Settles a completed deal. User.frozen -= amount (full deal amount,
        unchanged from the original 1:1 model). Of that same amount,
        Merchant.available += merchant_amount and User.available +=
        user_profit_amount (the user's own profit share) - the remainder
        (amount - merchant_amount - user_profit_amount) is never credited
        to any wallet here; it is recorded separately as OWNER profit by
        the caller (DealService), which has no wallet of its own. No money
        is created: merchant_amount + user_profit_amount can never exceed
        amount.
        """
        if not amount.is_finite() or amount <= 0:
            raise InvalidAmountError("amount must be a positive, finite number")
        if not merchant_amount.is_finite() or merchant_amount <= 0:
            raise InvalidAmountError("merchant_amount must be a positive, finite number")
        if not user_profit_amount.is_finite() or user_profit_amount < 0:
            raise InvalidAmountError("user_profit_amount must be a non-negative finite number")
        if merchant_amount + user_profit_amount > amount:
            raise InvalidAmountError(
                "merchant_amount + user_profit_amount cannot exceed the settled amount"
            )

        user_existing = await self._ledger.get_by_reference(
            reference_type="deal", reference_id=deal_id, entry_type=LedgerEntryType.DEAL_SETTLEMENT
        )
        merchant_existing = await self._ledger.get_by_reference(
            reference_type="deal",
            reference_id=deal_id,
            entry_type=LedgerEntryType.DEAL_SETTLEMENT_CREDIT,
        )
        profit_existing = await self._ledger.get_by_reference(
            reference_type="deal", reference_id=deal_id, entry_type=LedgerEntryType.DEAL_USER_PROFIT
        )
        if user_existing is not None and merchant_existing is not None:
            if user_profit_amount == 0 or profit_existing is not None:
                return user_existing, merchant_existing, profit_existing

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

        # 1. Update User wallet (frozen -= amount, full deal amount)
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

        # 2. Update Merchant wallet (available += merchant_amount, net of split)
        m_avail_before = merchant_wallet.available_balance
        m_held_before = merchant_wallet.held_balance

        merchant_wallet.available_balance = m_avail_before + merchant_amount
        await self._merchant_wallets.save(merchant_wallet)

        merchant_entry = LedgerEntry(
            merchant_wallet_id=merchant_wallet.id,
            account_id=merchant_account_id,
            type=LedgerEntryType.DEAL_SETTLEMENT_CREDIT,
            balance_bucket=BalanceBucket.AVAILABLE,
            currency=merchant_wallet.currency,
            amount=merchant_amount,
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

        # 3. Credit the accepting USER's own profit share, same wallet,
        # available bucket - re-fetch before/after since (1) already moved
        # available_before for this wallet.
        profit_entry: LedgerEntry | None = None
        if user_profit_amount > 0:
            p_avail_before = user_wallet.available_balance
            p_ins_before = user_wallet.insurance_balance
            p_froz_before = user_wallet.frozen_balance

            user_wallet.available_balance = p_avail_before + user_profit_amount
            await self._wallets.save(user_wallet)

            profit_entry = LedgerEntry(
                wallet_id=user_wallet.id,
                account_id=user_account_id,
                type=LedgerEntryType.DEAL_USER_PROFIT,
                balance_bucket=BalanceBucket.AVAILABLE,
                currency=user_wallet.currency,
                amount=user_profit_amount,
                available_before=p_avail_before,
                available_after=user_wallet.available_balance,
                insurance_before=p_ins_before,
                insurance_after=user_wallet.insurance_balance,
                frozen_before=p_froz_before,
                frozen_after=user_wallet.frozen_balance,
                reference_type="deal",
                reference_id=deal_id,
                description="User profit share from completed deal",
                created_by_account_id=actor_id,
            )
            profit_entry = await self._ledger.create(profit_entry)

        return user_entry, merchant_entry, profit_entry

    async def credit_team_lead_profit(
        self,
        *,
        team_lead_account_id: uuid.UUID,
        amount: Decimal,
        deal_id: uuid.UUID,
        actor_id: uuid.UUID | None = None,
    ) -> LedgerEntry:
        """Credits a TEAM_LEAD's own UserWallet with their 1.5% share of a
        completed deal. Deliberately separate from settle_deal() above -
        this money is funded by OWNER independently (per the confirmed
        business rule) and must never alter the Deal's own 100% split
        (merchant/user/owner amounts). Reference is the deal, not a
        team-lead-specific entity, since that's the actual event that
        earned it."""
        if not amount.is_finite() or amount <= 0:
            raise InvalidAmountError("amount must be a positive, finite number")

        existing = await self._ledger.get_by_reference(
            reference_type="deal", reference_id=deal_id, entry_type=LedgerEntryType.TEAM_LEAD_PROFIT
        )
        if existing is not None:
            return existing

        wallet = await self._wallets.get_by_account_id_for_update(team_lead_account_id)
        if wallet is None:
            raise WalletNotFoundError()

        available_before = wallet.available_balance
        insurance_before = wallet.insurance_balance
        frozen_before = wallet.frozen_balance

        wallet.available_balance = available_before + amount
        await self._wallets.save(wallet)

        entry = LedgerEntry(
            wallet_id=wallet.id,
            account_id=team_lead_account_id,
            type=LedgerEntryType.TEAM_LEAD_PROFIT,
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
            description="Team lead profit share from completed deal",
            created_by_account_id=actor_id,
        )
        return await self._ledger.create(entry)

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

    async def hold_for_user_withdrawal(
        self, *, user_id: uuid.UUID, amount: Decimal, withdrawal_id: uuid.UUID
    ) -> LedgerEntry:
        """Same contract as hold_for_withdrawal(), but reserves from a
        UserWallet's frozen_balance bucket (the same bucket freeze_for_deal
        uses) instead of a MerchantWallet's held_balance."""
        if not amount.is_finite() or amount <= 0:
            raise InvalidAmountError("amount must be a positive, finite number")

        existing = await self._ledger.get_by_reference(
            reference_type="withdrawal",
            reference_id=withdrawal_id,
            entry_type=LedgerEntryType.WITHDRAWAL_HOLD,
        )
        if existing is not None:
            return existing

        wallet = await self._wallets.get_by_account_id_for_update(user_id)
        if wallet is None:
            raise WalletNotFoundError()

        available_before = wallet.available_balance
        insurance_before = wallet.insurance_balance
        frozen_before = wallet.frozen_balance

        if available_before < amount:
            raise InsufficientBalanceError("insufficient available balance for withdrawal")

        wallet.available_balance = available_before - amount
        wallet.frozen_balance = frozen_before + amount
        await self._wallets.save(wallet)

        entry = LedgerEntry(
            wallet_id=wallet.id,
            account_id=user_id,
            type=LedgerEntryType.WITHDRAWAL_HOLD,
            balance_bucket=BalanceBucket.FROZEN,
            currency=wallet.currency,
            amount=amount,
            available_before=available_before,
            available_after=wallet.available_balance,
            insurance_before=insurance_before,
            insurance_after=wallet.insurance_balance,
            frozen_before=frozen_before,
            frozen_after=wallet.frozen_balance,
            reference_type="withdrawal",
            reference_id=withdrawal_id,
            description="Hold balance for withdrawal request",
            created_by_account_id=user_id,
        )
        return await self._ledger.create(entry)

    async def release_for_user_withdrawal(
        self,
        *,
        user_id: uuid.UUID,
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

        wallet = await self._wallets.get_by_account_id_for_update(user_id)
        if wallet is None:
            raise WalletNotFoundError()

        available_before = wallet.available_balance
        insurance_before = wallet.insurance_balance
        frozen_before = wallet.frozen_balance

        if frozen_before < amount:
            raise InsufficientBalanceError("insufficient frozen balance to release withdrawal")

        wallet.frozen_balance = frozen_before - amount
        wallet.available_balance = available_before + amount
        await self._wallets.save(wallet)

        entry = LedgerEntry(
            wallet_id=wallet.id,
            account_id=user_id,
            type=LedgerEntryType.WITHDRAWAL_RELEASE,
            balance_bucket=BalanceBucket.AVAILABLE,
            currency=wallet.currency,
            amount=amount,
            available_before=available_before,
            available_after=wallet.available_balance,
            insurance_before=insurance_before,
            insurance_after=wallet.insurance_balance,
            frozen_before=frozen_before,
            frozen_after=wallet.frozen_balance,
            reference_type="withdrawal",
            reference_id=withdrawal_id,
            description="Release frozen balance for rejected/cancelled withdrawal",
            created_by_account_id=actor_id,
        )
        return await self._ledger.create(entry)

    async def pay_for_user_withdrawal(
        self,
        *,
        user_id: uuid.UUID,
        amount: Decimal,
        withdrawal_id: uuid.UUID,
        actor_id: uuid.UUID,
    ) -> LedgerEntry:
        """Same contract as pay_withdrawal(), but finalizes from a
        UserWallet's frozen_balance bucket instead of a MerchantWallet's
        held_balance - the same bucket hold_for_user_withdrawal reserved
        into. The amount is not returned to available; it leaves the
        wallet entirely."""
        if not amount.is_finite() or amount <= 0:
            raise InvalidAmountError("amount must be a positive, finite number")

        existing = await self._ledger.get_by_reference(
            reference_type="withdrawal",
            reference_id=withdrawal_id,
            entry_type=LedgerEntryType.WITHDRAWAL_PAID,
        )
        if existing is not None:
            return existing

        wallet = await self._wallets.get_by_account_id_for_update(user_id)
        if wallet is None:
            raise WalletNotFoundError()

        available_before = wallet.available_balance
        insurance_before = wallet.insurance_balance
        frozen_before = wallet.frozen_balance

        if frozen_before < amount:
            raise InsufficientBalanceError("insufficient frozen balance to mark paid")

        wallet.frozen_balance = frozen_before - amount
        await self._wallets.save(wallet)

        entry = LedgerEntry(
            wallet_id=wallet.id,
            account_id=user_id,
            type=LedgerEntryType.WITHDRAWAL_PAID,
            balance_bucket=BalanceBucket.FROZEN,
            currency=wallet.currency,
            amount=-amount,
            available_before=available_before,
            available_after=wallet.available_balance,
            insurance_before=insurance_before,
            insurance_after=wallet.insurance_balance,
            frozen_before=frozen_before,
            frozen_after=wallet.frozen_balance,
            reference_type="withdrawal",
            reference_id=withdrawal_id,
            description="Final deduction of frozen funds upon paid withdrawal",
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
        idempotency_key: str,
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
        idempotency_key: str,
    ) -> LedgerEntry:
        if not idempotency_key:
            raise InvalidAmountError("idempotency_key is required")
        if not amount.is_finite() or amount == 0:
            raise InvalidAmountError("amount must be a non-zero, finite number")
        if require_positive and amount <= 0:
            raise InvalidAmountError("amount must be greater than zero")

        target = await self._accounts.get_by_id(target_account_id)
        if target is None or target.role != UserRole.USER:
            raise WalletNotFoundError()
        if not target.is_active:
            raise InactiveAccountError("cannot modify the wallet of an inactive account")

        # Row lock serializes concurrent requests targeting the same wallet:
        # a second caller blocks here until the first commits, so its own
        # dedupe lookup below always sees the first request's committed row.
        wallet = await self._wallets.get_by_account_id_for_update(target_account_id)
        if wallet is None:
            raise WalletNotFoundError()

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
        # The wallet row lock already serializes concurrent requests for the
        # same (wallet, idempotency_key), but the unique constraint on
        # ledger_entries(wallet_id, idempotency_key) is the real guarantee -
        # a SAVEPOINT lets a conflict there be handled as "already applied"
        # instead of aborting the whole request transaction.
        session = self._ledger.session
        try:
            async with session.begin_nested():
                session.add(entry)
                await session.flush()
        except IntegrityError:
            existing = await self._ledger.get_by_wallet_and_idempotency_key(
                wallet.id, idempotency_key
            )
            if existing is not None:
                return existing
            raise
        await session.refresh(entry)
        return entry
