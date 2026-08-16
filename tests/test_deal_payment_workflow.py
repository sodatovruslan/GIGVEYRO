import asyncio
from decimal import Decimal
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums.account import UserRole
from app.enums.appeal import AppealReason, AppealStatus
from app.enums.deal import DealStatus
from app.enums.wallet import Currency
from app.models.account import Account
from app.models.merchant_wallet import MerchantWallet
from app.models.payment_requisite import PaymentRequisite
from app.models.traffic import UserTrafficSettings
from app.models.wallet import UserWallet
from app.repositories.account import AccountRepository
from app.repositories.appeal import AppealRepository
from app.repositories.deal import DealRepository
from app.repositories.ledger import LedgerRepository
from app.repositories.merchant_wallet import MerchantWalletRepository
from app.repositories.payment_requisite import PaymentRequisiteRepository
from app.repositories.traffic import TrafficRepository
from app.repositories.wallet import WalletRepository
from app.services.appeal import AppealService
from app.services.deal import DealNotFoundError, DealService, InvalidDealTransitionError
from app.services.exchange_rate import ConfiguredExchangeRateProvider
from app.services.wallet import WalletService


@pytest.fixture
def wallet_service(db_session: AsyncSession) -> WalletService:
    return WalletService(
        WalletRepository(db_session),
        LedgerRepository(db_session),
        AccountRepository(db_session),
        MerchantWalletRepository(db_session),
    )


@pytest.fixture
def appeal_service(db_session: AsyncSession, wallet_service: WalletService) -> AppealService:
    return AppealService(
        AppealRepository(db_session),
        DealRepository(db_session),
        wallet_service,
    )


@pytest.fixture
def deal_service(
    db_session: AsyncSession, wallet_service: WalletService, appeal_service: AppealService
) -> DealService:
    return DealService(
        DealRepository(db_session),
        PaymentRequisiteRepository(db_session),
        TrafficRepository(db_session),
        AccountRepository(db_session),
        wallet_service,
        ConfiguredExchangeRateProvider(),
        appeal_service=appeal_service,
    )


@pytest_asyncio.fixture
async def setup_accounts(db_session: AsyncSession):
    merchant = Account(
        username="merchant_pwf",
        email="merchant_pwf@example.com",
        role=UserRole.MERCHANT,
        is_active=True,
    )
    user = Account(
        username="user_pwf",
        email="user_pwf@example.com",
        role=UserRole.USER,
        is_active=True,
    )
    owner = Account(
        username="owner_pwf",
        email="owner_pwf@example.com",
        role=UserRole.OWNER,
        is_active=True,
    )
    db_session.add_all([merchant, user, owner])
    await db_session.flush()

    m_wallet = MerchantWallet(
        account_id=merchant.id, currency=Currency.USDT, available_balance=Decimal("0")
    )
    u_wallet = UserWallet(
        account_id=user.id, currency=Currency.USDT, available_balance=Decimal("100.00000000")
    )
    traffic = UserTrafficSettings(account_id=user.id, is_enabled=True)
    requisite = PaymentRequisite(
        account_id=user.id,
        type="card",
        bank_name="TestBank",
        holder_name="Holder Name",
        card_number="4444555566667777",
        is_active=True,
    )
    db_session.add_all([m_wallet, u_wallet, traffic, requisite])
    await db_session.commit()
    await db_session.refresh(merchant)
    await db_session.refresh(user)
    await db_session.refresh(owner)
    await db_session.refresh(requisite)
    return merchant, user, owner, requisite


@pytest.mark.asyncio
async def test_merchant_mark_paid_success(
    setup_accounts,
    deal_service: DealService,
    wallet_service: WalletService,
):
    merchant, user, owner, requisite = setup_accounts

    deal = await deal_service.create_deal(merchant, amount_tjs=Decimal("100.00"))
    deal = await deal_service.accept_deal(
        account=user, deal_id=deal.id, requisite_id=requisite.id
    )

    deal_paid = await deal_service.mark_paid_by_merchant(
        merchant.id, deal.id, payment_reference="REF123456", payment_note="Paid via app"
    )

    assert deal_paid.status == DealStatus.PAYMENT_PENDING
    assert deal_paid.merchant_marked_paid_at is not None
    assert deal_paid.payment_reference == "REF123456"
    assert deal_paid.payment_note == "Paid via app"

    # Verify funds unchanged on mark-paid
    u_wallet = await wallet_service.get_wallet_for_account(user.id)
    assert u_wallet.available_balance == Decimal("90.00000000")
    assert u_wallet.frozen_balance == Decimal("10.00000000")


@pytest.mark.asyncio
async def test_user_confirm_received_success(
    setup_accounts,
    deal_service: DealService,
    wallet_service: WalletService,
):
    merchant, user, owner, requisite = setup_accounts

    deal = await deal_service.create_deal(merchant, amount_tjs=Decimal("100.00"))
    deal = await deal_service.accept_deal(
        account=user, deal_id=deal.id, requisite_id=requisite.id
    )
    await deal_service.mark_paid_by_merchant(merchant.id, deal.id)

    deal_completed = await deal_service.confirm_received_by_user(user, deal.id)

    assert deal_completed.status == DealStatus.COMPLETED
    assert deal_completed.user_confirmed_received_at is not None

    u_wallet = await wallet_service.get_wallet_for_account(user.id)
    assert u_wallet.available_balance == Decimal("90.00000000")
    assert u_wallet.frozen_balance == Decimal("0.00000000")

    m_wallet = await wallet_service.get_merchant_wallet_for_account(merchant.id)
    assert m_wallet.available_balance == Decimal("10.00000000")


@pytest.mark.asyncio
async def test_user_report_payment_problem_creates_appeal(
    setup_accounts,
    deal_service: DealService,
    wallet_service: WalletService,
    appeal_service: AppealService,
):
    merchant, user, owner, requisite = setup_accounts

    deal = await deal_service.create_deal(merchant, amount_tjs=Decimal("100.00"))
    deal = await deal_service.accept_deal(
        account=user, deal_id=deal.id, requisite_id=requisite.id
    )
    await deal_service.mark_paid_by_merchant(merchant.id, deal.id)

    deal_disputed, appeal = await deal_service.report_payment_problem_by_user(
        user,
        deal.id,
        reason_code=AppealReason.PAYMENT_NOT_RECEIVED,
        message="Did not receive payment in bank account.",
    )

    assert deal_disputed.status == DealStatus.DISPUTED
    assert deal_disputed.user_rejected_payment_at is not None
    assert appeal is not None
    assert appeal.status == AppealStatus.OPEN

    # Frozen funds remain protected
    u_wallet = await wallet_service.get_wallet_for_account(user.id)
    assert u_wallet.available_balance == Decimal("90.00000000")
    assert u_wallet.frozen_balance == Decimal("10.00000000")


@pytest.mark.asyncio
async def test_invalid_transitions_payment_workflow(
    setup_accounts,
    deal_service: DealService,
):
    merchant, user, owner, requisite = setup_accounts

    deal = await deal_service.create_deal(merchant, amount_tjs=Decimal("100.00"))

    # Cannot mark paid when AVAILABLE
    with pytest.raises(InvalidDealTransitionError):
        await deal_service.mark_paid_by_merchant(merchant.id, deal.id)

    # Cannot confirm received when AVAILABLE
    with pytest.raises(InvalidDealTransitionError):
        await deal_service.confirm_received_by_user(user, deal.id)
