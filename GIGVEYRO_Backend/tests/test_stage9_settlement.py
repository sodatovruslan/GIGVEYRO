import asyncio
import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.db.session import engine
from app.enums.account import UserRole
from app.enums.deal import DealStatus
from app.enums.wallet import LedgerEntryType
from app.models.account import Account
from app.models.deal import Deal
from app.models.ledger import LedgerEntry
from app.models.merchant_wallet import MerchantWallet
from app.models.wallet import UserWallet
from app.repositories.account import AccountRepository
from app.models.fees import FeeSnapshot, OwnerProfitEntry
from app.repositories.deal import DealRepository
from app.repositories.fees import FeeRepository
from app.repositories.ledger import LedgerRepository
from app.repositories.merchant_wallet import MerchantWalletRepository
from app.repositories.payment_requisite import PaymentRequisiteRepository
from app.repositories.traffic import TrafficRepository
from app.repositories.wallet import WalletRepository
from app.services.account import AccountService
from app.services.deal import DealService
from app.services.exchange_rate import ConfiguredExchangeRateProvider
from app.services.traffic import TrafficService
from app.services.wallet import WalletService


@pytest.mark.asyncio
async def test_merchant_wallet_created_on_account_creation(db_session: AsyncSession):
    account_repo = AccountRepository(db_session)
    wallet_service = WalletService(
        WalletRepository(db_session),
        LedgerRepository(db_session),
        account_repo,
        MerchantWalletRepository(db_session),
    )
    traffic_service = TrafficService(
        TrafficRepository(db_session), PaymentRequisiteRepository(db_session), account_repo
    )
    account_service = AccountService(account_repo, wallet_service, traffic_service)

    merchant = await account_service.create_managed_account(
        username=f"merch_{uuid.uuid4().hex[:8]}",
        password="Password123!",
        role=UserRole.MERCHANT,
        full_name="Test Merchant",
        email=f"merch_{uuid.uuid4().hex[:8]}@example.com",
        phone=None,
    )

    wallet = await wallet_service.get_merchant_wallet_for_account(merchant.id)
    assert wallet is not None
    assert wallet.available_balance == Decimal("0")


@pytest.mark.asyncio
async def test_successful_settlement_flow(
    db_session: AsyncSession, make_account, make_wallet, make_merchant_wallet, make_deal
):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("0"), frozen=Decimal("50"))

    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant, available=Decimal("100"))

    deal = await make_deal(
        merchant,
        status=DealStatus.ACCEPTED,
        user=user,
        amount_usdt=Decimal("20"),
    )

    account_repo = AccountRepository(db_session)
    wallet_service = WalletService(
        WalletRepository(db_session),
        LedgerRepository(db_session),
        account_repo,
        MerchantWalletRepository(db_session),
    )
    fee_repo = FeeRepository(db_session)
    deal_service = DealService(
        deal_repository=DealRepository(db_session),
        requisite_repository=PaymentRequisiteRepository(db_session),
        traffic_repository=TrafficRepository(db_session),
        account_repository=account_repo,
        wallet_service=wallet_service,
        rate_provider=ConfiguredExchangeRateProvider(),
        fee_repository=fee_repo,
    )

    completed_deal = await deal_service.complete_deal(deal.id)
    assert completed_deal.status == DealStatus.COMPLETED
    assert completed_deal.completed_at is not None

    # Deal = 20 USDT: owner 7% = 1.40, user profit 10% = 2.00, merchant net
    # = 20 - 1.40 - 2.00 = 16.60. Nothing is created or lost: 16.60 + 2.00
    # + 1.40 == 20.00 exactly.
    assert completed_deal.merchant_settlement_amount == Decimal("16.60000000")
    assert completed_deal.user_profit_amount == Decimal("2.00000000")
    assert completed_deal.owner_profit_amount == Decimal("1.40000000")

    u_wallet = await wallet_service.get_wallet_for_account(user.id)
    assert u_wallet.frozen_balance == Decimal("30")
    assert u_wallet.available_balance == Decimal("2.00000000")

    updated_m_wallet = await wallet_service.get_merchant_wallet_for_account(merchant.id)
    assert updated_m_wallet.available_balance == Decimal("116.60000000")

    u_ledger, _ = await wallet_service.get_ledger_for_account(
        user.id,
        entry_type=LedgerEntryType.DEAL_SETTLEMENT,
        date_from=None,
        date_to=None,
        limit=10,
        offset=0,
    )
    assert len(u_ledger) == 1
    assert u_ledger[0].amount == Decimal("-20")

    profit_ledger, _ = await wallet_service.get_ledger_for_account(
        user.id,
        entry_type=LedgerEntryType.DEAL_USER_PROFIT,
        date_from=None,
        date_to=None,
        limit=10,
        offset=0,
    )
    assert len(profit_ledger) == 1
    assert profit_ledger[0].amount == Decimal("2.00000000")

    m_ledger, _ = await wallet_service.get_ledger_for_account(
        merchant.id,
        entry_type=LedgerEntryType.DEAL_SETTLEMENT_CREDIT,
        date_from=None,
        date_to=None,
        limit=10,
        offset=0,
    )
    assert len(m_ledger) == 1
    assert m_ledger[0].amount == Decimal("16.60000000")

    owner_entry = await fee_repo.get_profit_by_source(
        source_type="deal", source_id=deal.id, fee_type="deal_fee"
    )
    assert owner_entry is not None
    assert owner_entry.fee_amount == Decimal("1.40000000")
    assert owner_entry.gross_amount == Decimal("20.00000000")


@pytest.mark.asyncio
async def test_successful_release_flow(
    db_session: AsyncSession, make_account, make_wallet, make_merchant_wallet, make_deal
):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("100"), frozen=Decimal("50"))

    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant, available=Decimal("0"))

    deal = await make_deal(
        merchant,
        status=DealStatus.ACCEPTED,
        user=user,
        amount_usdt=Decimal("20"),
    )

    account_repo = AccountRepository(db_session)
    wallet_service = WalletService(
        WalletRepository(db_session),
        LedgerRepository(db_session),
        account_repo,
        MerchantWalletRepository(db_session),
    )
    deal_service = DealService(
        deal_repository=DealRepository(db_session),
        requisite_repository=PaymentRequisiteRepository(db_session),
        traffic_repository=TrafficRepository(db_session),
        account_repository=account_repo,
        wallet_service=wallet_service,
        rate_provider=ConfiguredExchangeRateProvider(),
        fee_repository=FeeRepository(db_session),
    )

    released_deal = await deal_service.cancel_or_release_deal(deal.id)
    assert released_deal.status == DealStatus.CANCELLED
    assert released_deal.cancelled_at is not None

    u_wallet = await wallet_service.get_wallet_for_account(user.id)
    assert u_wallet.frozen_balance == Decimal("30")
    assert u_wallet.available_balance == Decimal("120")

    updated_m_wallet = await wallet_service.get_merchant_wallet_for_account(merchant.id)
    assert updated_m_wallet.available_balance == Decimal("0")


@pytest.mark.asyncio
async def test_settlement_idempotency(
    db_session: AsyncSession, make_account, make_wallet, make_merchant_wallet, make_deal
):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("0"), frozen=Decimal("50"))

    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant, available=Decimal("100"))

    deal = await make_deal(
        merchant,
        status=DealStatus.ACCEPTED,
        user=user,
        amount_usdt=Decimal("20"),
    )

    account_repo = AccountRepository(db_session)
    wallet_service = WalletService(
        WalletRepository(db_session),
        LedgerRepository(db_session),
        account_repo,
        MerchantWalletRepository(db_session),
    )
    fee_repo = FeeRepository(db_session)
    deal_service = DealService(
        deal_repository=DealRepository(db_session),
        requisite_repository=PaymentRequisiteRepository(db_session),
        traffic_repository=TrafficRepository(db_session),
        account_repository=account_repo,
        wallet_service=wallet_service,
        rate_provider=ConfiguredExchangeRateProvider(),
        fee_repository=fee_repo,
    )

    res1 = await deal_service.complete_deal(deal.id)
    res2 = await deal_service.complete_deal(deal.id)

    assert res1.status == DealStatus.COMPLETED
    assert res2.status == DealStatus.COMPLETED

    u_wallet = await wallet_service.get_wallet_for_account(user.id)
    assert u_wallet.frozen_balance == Decimal("30")
    # Double-complete must not double-credit the user's profit share.
    assert u_wallet.available_balance == Decimal("2.00000000")

    m_wallet = await wallet_service.get_merchant_wallet_for_account(merchant.id)
    assert m_wallet.available_balance == Decimal("116.60000000")

    owner_entries, total = await fee_repo.list_profit_entries(
        date_from=None,
        date_to=None,
        fee_type="deal_fee",
        currency=None,
        source_type="deal",
        source_id=deal.id,
        limit=10,
        offset=0,
    )
    assert total == 1
    assert owner_entries[0].fee_amount == Decimal("1.40000000")


@pytest.mark.asyncio
async def test_concurrency_two_completes(
    make_account, make_wallet, make_merchant_wallet, make_deal
):
    """Real concurrency test using isolated database sessions for completion."""
    async with engine.connect() as conn1, engine.connect() as conn2:
        s1 = AsyncSession(bind=conn1, expire_on_commit=False)
        s2 = AsyncSession(bind=conn2, expire_on_commit=False)

        try:
            user = Account(
                username=f"u_conc_{uuid.uuid4().hex[:8]}",
                password_hash="hash",
                role=UserRole.USER,
                full_name="User",
                is_active=True,
            )
            merchant = Account(
                username=f"m_conc_{uuid.uuid4().hex[:8]}",
                password_hash="hash",
                role=UserRole.MERCHANT,
                full_name="Merchant",
                is_active=True,
            )
            s1.add_all([user, merchant])
            await s1.flush()

            u_wallet = UserWallet(
                account_id=user.id, available_balance=Decimal("0"), frozen_balance=Decimal("20")
            )
            m_wallet = MerchantWallet(account_id=merchant.id, available_balance=Decimal("0"))
            deal = Deal(
                public_id=f"D-{uuid.uuid4().hex[:6].upper()}",
                merchant_id=merchant.id,
                user_id=user.id,
                amount_tjs=Decimal("200"),
                amount_usdt=Decimal("20"),
                status=DealStatus.ACCEPTED,
                expires_at=user.created_at,
            )
            s1.add_all([u_wallet, m_wallet, deal])
            await s1.commit()

            deal_id = deal.id

            async def do_complete(session: AsyncSession):
                account_repo = AccountRepository(session)
                ws = WalletService(
                    WalletRepository(session),
                    LedgerRepository(session),
                    account_repo,
                    MerchantWalletRepository(session),
                )
                ds = DealService(
                    deal_repository=DealRepository(session),
                    requisite_repository=PaymentRequisiteRepository(session),
                    traffic_repository=TrafficRepository(session),
                    account_repository=account_repo,
                    wallet_service=ws,
                    rate_provider=ConfiguredExchangeRateProvider(),
                    fee_repository=FeeRepository(session),
                )
                res = await ds.complete_deal(deal_id)
                await session.commit()
                return res

            res1, res2 = await asyncio.gather(
                do_complete(s1), do_complete(s2), return_exceptions=True
            )

            assert not isinstance(res1, Exception)
            assert not isinstance(res2, Exception)

            async with AsyncSession(bind=engine) as verify_session:
                final_u_wallet = (
                    await verify_session.execute(
                        select(UserWallet).where(UserWallet.account_id == user.id)
                    )
                ).scalar_one()
                final_m_wallet = (
                    await verify_session.execute(
                        select(MerchantWallet).where(MerchantWallet.account_id == merchant.id)
                    )
                ).scalar_one()

                assert final_u_wallet.frozen_balance == Decimal("0")
                # Deal = 20: owner 1.40 + user profit 2.00 + merchant net
                # 16.60 == 20 exactly, and - the actual point of this test -
                # neither concurrent complete_deal() call duplicated any
                # of the three shares.
                assert final_u_wallet.available_balance == Decimal("2.00000000")
                assert final_m_wallet.available_balance == Decimal("16.60000000")

                owner_entries = (
                    await verify_session.execute(
                        select(OwnerProfitEntry).where(
                            OwnerProfitEntry.source_type == "deal",
                            OwnerProfitEntry.source_id == deal_id,
                        )
                    )
                ).scalars().all()
                assert len(owner_entries) == 1
                assert owner_entries[0].fee_amount == Decimal("1.40000000")

                await verify_session.execute(
                    delete(OwnerProfitEntry).where(OwnerProfitEntry.source_id == deal_id)
                )
                await verify_session.execute(
                    delete(FeeSnapshot).where(FeeSnapshot.source_id == deal_id)
                )
                await verify_session.execute(
                    delete(LedgerEntry).where(LedgerEntry.account_id.in_([user.id, merchant.id]))
                )
                await verify_session.execute(delete(Deal).where(Deal.id == deal_id))
                await verify_session.execute(
                    delete(UserWallet).where(UserWallet.account_id == user.id)
                )
                await verify_session.execute(
                    delete(MerchantWallet).where(MerchantWallet.account_id == merchant.id)
                )
                await verify_session.execute(
                    delete(Account).where(Account.id.in_([user.id, merchant.id]))
                )
                await verify_session.commit()
        finally:
            await s1.close()
            await s2.close()


@pytest.mark.asyncio
async def test_merchant_wallet_endpoints(
    client: AsyncClient, db_session: AsyncSession, make_account, make_merchant_wallet
):
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant, available=Decimal("150.5"))

    token = create_access_token(merchant.id, role=UserRole.MERCHANT)
    headers = {"Authorization": f"Bearer {token}"}

    response = await client.get("/merchant/wallet", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["currency"] == "USDT"
    assert Decimal(str(data["available_balance"])) == Decimal("150.5")

    response_ledger = await client.get("/merchant/wallet/ledger", headers=headers)
    assert response_ledger.status_code == 200
    ledger_data = response_ledger.json()
    assert "items" in ledger_data
    assert ledger_data["total"] == 0
