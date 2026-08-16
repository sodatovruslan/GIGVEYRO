import asyncio
from decimal import Decimal
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.enums.account import UserRole
from app.enums.wallet import BalanceBucket, Currency, LedgerEntryType
from app.enums.withdrawal import WithdrawalDestinationType, WithdrawalStatus
from app.models.account import Account
from app.models.merchant_wallet import MerchantWallet
from app.repositories.account import AccountRepository
from app.repositories.ledger import LedgerRepository
from app.repositories.merchant_wallet import MerchantWalletRepository
from app.repositories.wallet import WalletRepository
from app.repositories.withdrawal import WithdrawalRepository
from app.services.wallet import InsufficientBalanceError, WalletService
from app.services.withdrawal import (
    InvalidDestinationError,
    InvalidWithdrawalTransitionError,
    WithdrawalCreationNotAllowedError,
    WithdrawalNotFoundError,
    WithdrawalService,
)


@pytest.fixture
def wallet_service(db_session: AsyncSession) -> WalletService:
    account_repo = AccountRepository(db_session)
    wallet_repo = WalletRepository(db_session)
    ledger_repo = LedgerRepository(db_session)
    merchant_wallet_repo = MerchantWalletRepository(db_session)
    return WalletService(wallet_repo, ledger_repo, account_repo, merchant_wallet_repo)


@pytest.fixture
def withdrawal_service(db_session: AsyncSession, wallet_service: WalletService) -> WithdrawalService:
    account_repo = AccountRepository(db_session)
    withdrawal_repo = WithdrawalRepository(db_session)
    return WithdrawalService(withdrawal_repo, wallet_service, account_repo)


@pytest_asyncio.fixture
async def merchant_account(db_session: AsyncSession) -> Account:
    account = Account(
        username="test_merchant_wd",
        email="merchant_wd@example.com",
        role=UserRole.MERCHANT,
        is_active=True,
    )
    db_session.add(account)
    await db_session.flush()

    wallet = MerchantWallet(
        account_id=account.id,
        currency=Currency.USDT,
        available_balance=Decimal("100.00000000"),
        held_balance=Decimal("0.00000000"),
    )
    db_session.add(wallet)
    await db_session.commit()
    await db_session.refresh(account)
    return account


@pytest_asyncio.fixture
async def owner_account(db_session: AsyncSession) -> Account:
    account = Account(
        username="test_owner_wd",
        email="owner_wd@example.com",
        role=UserRole.OWNER,
        is_active=True,
    )
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)
    return account


@pytest.mark.asyncio
async def test_create_withdrawal_success(
    merchant_account: Account,
    withdrawal_service: WithdrawalService,
    wallet_service: WalletService,
):
    wd = await withdrawal_service.create_withdrawal(
        merchant_account,
        amount=Decimal("40.00000000"),
        destination_type=WithdrawalDestinationType.USDT_TRC20_ADDRESS,
        destination="T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb",
    )

    assert wd.status == WithdrawalStatus.PENDING
    assert wd.amount == Decimal("40.00000000")

    wallet = await wallet_service.get_merchant_wallet_for_account(merchant_account.id)
    assert wallet.available_balance == Decimal("60.00000000")
    assert wallet.held_balance == Decimal("40.00000000")


@pytest.mark.asyncio
async def test_create_withdrawal_insufficient_balance(
    merchant_account: Account,
    withdrawal_service: WithdrawalService,
):
    with pytest.raises(InsufficientBalanceError):
        await withdrawal_service.create_withdrawal(
            merchant_account,
            amount=Decimal("150.00000000"),
            destination_type=WithdrawalDestinationType.USDT_TRC20_ADDRESS,
            destination="T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb",
        )


@pytest.mark.asyncio
async def test_owner_approve_and_mark_paid(
    merchant_account: Account,
    owner_account: Account,
    withdrawal_service: WithdrawalService,
    wallet_service: WalletService,
):
    wd = await withdrawal_service.create_withdrawal(
        merchant_account,
        amount=Decimal("40.00000000"),
        destination_type=WithdrawalDestinationType.USDT_TRC20_ADDRESS,
        destination="T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb",
    )

    # Approve
    wd_approved = await withdrawal_service.approve_by_owner(
        owner_account.id, wd.id, comment="Approved by owner"
    )
    assert wd_approved.status == WithdrawalStatus.APPROVED
    wallet = await wallet_service.get_merchant_wallet_for_account(merchant_account.id)
    assert wallet.available_balance == Decimal("60.00000000")
    assert wallet.held_balance == Decimal("40.00000000")

    # Mark Paid
    wd_paid = await withdrawal_service.mark_paid_by_owner(
        owner_account.id, wd.id, comment="Paid TRC20"
    )
    assert wd_paid.status == WithdrawalStatus.PAID
    wallet = await wallet_service.get_merchant_wallet_for_account(merchant_account.id)
    assert wallet.available_balance == Decimal("60.00000000")
    assert wallet.held_balance == Decimal("0.00000000")


@pytest.mark.asyncio
async def test_owner_reject_refunds_funds(
    merchant_account: Account,
    owner_account: Account,
    withdrawal_service: WithdrawalService,
    wallet_service: WalletService,
):
    wd = await withdrawal_service.create_withdrawal(
        merchant_account,
        amount=Decimal("40.00000000"),
        destination_type=WithdrawalDestinationType.USDT_TRC20_ADDRESS,
        destination="T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb",
    )

    wd_rejected = await withdrawal_service.reject_by_owner(
        owner_account.id, wd.id, comment="Invalid destination"
    )
    assert wd_rejected.status == WithdrawalStatus.REJECTED

    wallet = await wallet_service.get_merchant_wallet_for_account(merchant_account.id)
    assert wallet.available_balance == Decimal("100.00000000")
    assert wallet.held_balance == Decimal("0.00000000")


@pytest.mark.asyncio
async def test_merchant_cancel_refunds_funds(
    merchant_account: Account,
    withdrawal_service: WithdrawalService,
    wallet_service: WalletService,
):
    wd = await withdrawal_service.create_withdrawal(
        merchant_account,
        amount=Decimal("40.00000000"),
        destination_type=WithdrawalDestinationType.USDT_TRC20_ADDRESS,
        destination="T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb",
    )

    wd_cancelled = await withdrawal_service.cancel_by_merchant(merchant_account.id, wd.id)
    assert wd_cancelled.status == WithdrawalStatus.CANCELLED

    wallet = await wallet_service.get_merchant_wallet_for_account(merchant_account.id)
    assert wallet.available_balance == Decimal("100.00000000")
    assert wallet.held_balance == Decimal("0.00000000")


@pytest.mark.asyncio
async def test_invalid_transitions(
    merchant_account: Account,
    owner_account: Account,
    withdrawal_service: WithdrawalService,
):
    wd = await withdrawal_service.create_withdrawal(
        merchant_account,
        amount=Decimal("40.00000000"),
        destination_type=WithdrawalDestinationType.USDT_TRC20_ADDRESS,
        destination="T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb",
    )

    # Cannot mark paid directly from pending
    with pytest.raises(InvalidWithdrawalTransitionError):
        await withdrawal_service.mark_paid_by_owner(owner_account.id, wd.id)

    await withdrawal_service.cancel_by_merchant(merchant_account.id, wd.id)

    # Cannot approve cancelled
    with pytest.raises(InvalidWithdrawalTransitionError):
        await withdrawal_service.approve_by_owner(owner_account.id, wd.id)
