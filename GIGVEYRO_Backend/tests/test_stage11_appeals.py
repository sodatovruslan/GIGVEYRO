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
from app.enums.appeal import AppealReason, AppealResolution, AppealStatus
from app.enums.deal import DealStatus
from app.models.account import Account
from app.models.appeal import DealAppeal
from app.models.deal import Deal
from app.models.merchant_wallet import MerchantWallet
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
from app.services.deal import DealService, InvalidDealTransitionError
from app.services.exchange_rate import ConfiguredExchangeRateProvider
from app.services.wallet import WalletService


@pytest.fixture
def make_appeal_service(db_session: AsyncSession):
    account_repo = AccountRepository(db_session)
    wallet_service = WalletService(
        WalletRepository(db_session),
        LedgerRepository(db_session),
        account_repo,
        MerchantWalletRepository(db_session),
    )
    return AppealService(
        appeal_repository=AppealRepository(db_session),
        deal_repository=DealRepository(db_session),
        wallet_service=wallet_service,
    )


@pytest.mark.asyncio
async def test_open_appeal_user_success(
    db_session: AsyncSession,
    make_account,
    make_wallet,
    make_merchant_wallet,
    make_deal,
    make_appeal_service,
):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("0"), frozen=Decimal("20"))

    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant, available=Decimal("0"))

    deal = await make_deal(
        merchant, status=DealStatus.ACCEPTED, user=user, amount_usdt=Decimal("20")
    )

    appeal = await make_appeal_service.open_appeal(
        user,
        deal_id=deal.id,
        reason_code=AppealReason.PAYMENT_NOT_RECEIVED,
        message="Merchant says payment was not received",
    )

    assert appeal.status == AppealStatus.OPEN
    assert appeal.previous_deal_status == DealStatus.ACCEPTED

    d = await db_session.get(Deal, deal.id)
    assert d.status == DealStatus.DISPUTED

    u_w = await db_session.execute(select(UserWallet).where(UserWallet.account_id == user.id))
    assert u_w.scalar_one().frozen_balance == Decimal("20")


@pytest.mark.asyncio
async def test_disputed_deal_cannot_complete_or_release_directly(
    db_session: AsyncSession,
    make_account,
    make_wallet,
    make_merchant_wallet,
    make_deal,
    make_appeal_service,
):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("0"), frozen=Decimal("20"))

    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant, available=Decimal("0"))

    deal = await make_deal(
        merchant, status=DealStatus.ACCEPTED, user=user, amount_usdt=Decimal("20")
    )

    await make_appeal_service.open_appeal(
        user,
        deal_id=deal.id,
        reason_code=AppealReason.PAYMENT_NOT_RECEIVED,
        message="Disputed deal test",
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
    )

    with pytest.raises(InvalidDealTransitionError):
        await deal_service.complete_deal(deal.id)

    with pytest.raises(InvalidDealTransitionError):
        await deal_service.cancel_or_release_deal(deal.id)


@pytest.mark.asyncio
async def test_cancel_appeal_restores_previous_deal_status(
    db_session: AsyncSession,
    make_account,
    make_wallet,
    make_merchant_wallet,
    make_deal,
    make_appeal_service,
):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("0"), frozen=Decimal("20"))

    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant, available=Decimal("0"))

    deal = await make_deal(
        merchant, status=DealStatus.ACCEPTED, user=user, amount_usdt=Decimal("20")
    )

    appeal = await make_appeal_service.open_appeal(
        user,
        deal_id=deal.id,
        reason_code=AppealReason.PAYMENT_NOT_RECEIVED,
        message="Accidental appeal",
    )

    cancelled_appeal = await make_appeal_service.cancel_appeal(user, appeal_id=appeal.id)
    assert cancelled_appeal.status == AppealStatus.CANCELLED

    d = await db_session.get(Deal, deal.id)
    assert d.status == DealStatus.ACCEPTED


@pytest.mark.asyncio
async def test_resolve_release_to_user(
    db_session: AsyncSession,
    make_account,
    make_wallet,
    make_merchant_wallet,
    make_deal,
    make_appeal_service,
):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("0"), frozen=Decimal("20"))

    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant, available=Decimal("0"))

    owner = await make_account(role=UserRole.OWNER)

    deal = await make_deal(
        merchant, status=DealStatus.ACCEPTED, user=user, amount_usdt=Decimal("20")
    )

    appeal = await make_appeal_service.open_appeal(
        user,
        deal_id=deal.id,
        reason_code=AppealReason.PAYMENT_NOT_RECEIVED,
        message="Did not receive payment",
    )

    resolved = await make_appeal_service.resolve_appeal(
        owner.id,
        appeal.id,
        resolution=AppealResolution.RELEASE_TO_USER,
        owner_note="User provided valid proof of non-payment",
    )

    assert resolved.status == AppealStatus.RESOLVED
    assert resolved.resolution == AppealResolution.RELEASE_TO_USER

    d = await db_session.get(Deal, deal.id)
    assert d.status == DealStatus.CANCELLED

    u_w = (
        await db_session.execute(select(UserWallet).where(UserWallet.account_id == user.id))
    ).scalar_one()
    assert u_w.frozen_balance == Decimal("0")
    assert u_w.available_balance == Decimal("20")


@pytest.mark.asyncio
async def test_resolve_settle_to_merchant(
    db_session: AsyncSession,
    make_account,
    make_wallet,
    make_merchant_wallet,
    make_deal,
    make_appeal_service,
):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("0"), frozen=Decimal("20"))

    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant, available=Decimal("0"))

    owner = await make_account(role=UserRole.OWNER)

    deal = await make_deal(
        merchant, status=DealStatus.ACCEPTED, user=user, amount_usdt=Decimal("20")
    )

    appeal = await make_appeal_service.open_appeal(
        merchant,
        deal_id=deal.id,
        reason_code=AppealReason.WRONG_AMOUNT,
        message="User sent less money",
    )

    resolved = await make_appeal_service.resolve_appeal(
        owner.id,
        appeal.id,
        resolution=AppealResolution.SETTLE_TO_MERCHANT,
        owner_note="Merchant is correct, settling deal",
    )

    assert resolved.status == AppealStatus.RESOLVED
    assert resolved.resolution == AppealResolution.SETTLE_TO_MERCHANT

    d = await db_session.get(Deal, deal.id)
    assert d.status == DealStatus.COMPLETED

    u_w = (
        await db_session.execute(select(UserWallet).where(UserWallet.account_id == user.id))
    ).scalar_one()
    assert u_w.frozen_balance == Decimal("0")

    m_w = (
        await db_session.execute(
            select(MerchantWallet).where(MerchantWallet.account_id == merchant.id)
        )
    ).scalar_one()
    assert m_w.available_balance == Decimal("20")


@pytest.mark.asyncio
async def test_concurrency_double_open_appeal():
    """Real DB concurrency test: USER and MERCHANT try opening an appeal simultaneously."""
    async with engine.connect() as conn1, engine.connect() as conn2:
        tx1 = await conn1.begin()
        tx2 = await conn2.begin()

        s1 = AsyncSession(bind=conn1, expire_on_commit=False)
        s2 = AsyncSession(bind=conn2, expire_on_commit=False)

        try:
            user = Account(
                username=f"u_app_{uuid.uuid4().hex[:8]}",
                password_hash="hash",
                role=UserRole.USER,
                full_name="User Appeal",
                is_active=True,
            )
            merchant = Account(
                username=f"m_app_{uuid.uuid4().hex[:8]}",
                password_hash="hash",
                role=UserRole.MERCHANT,
                full_name="Merchant Appeal",
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
            u_id = user.id
            m_id = merchant.id

            async def do_open(session: AsyncSession, account_id: uuid.UUID):
                account_repo = AccountRepository(session)
                ws = WalletService(
                    WalletRepository(session),
                    LedgerRepository(session),
                    account_repo,
                    MerchantWalletRepository(session),
                )
                service = AppealService(
                    appeal_repository=AppealRepository(session),
                    deal_repository=DealRepository(session),
                    wallet_service=ws,
                )
                act = await account_repo.get_by_id(account_id)
                res = await service.open_appeal(
                    act,
                    deal_id=deal_id,
                    reason_code=AppealReason.PAYMENT_NOT_RECEIVED,
                    message="Concurrent open test",
                )
                await session.commit()
                return res

            results = await asyncio.gather(
                do_open(s1, u_id), do_open(s2, m_id), return_exceptions=True
            )

            successes = [r for r in results if not isinstance(r, Exception)]
            failures = [r for r in results if isinstance(r, Exception)]

            assert len(successes) == 1
            assert len(failures) == 1

            if not isinstance(results[0], Exception):
                await tx2.rollback()
                await tx1.commit()
            else:
                await tx1.rollback()
                await tx2.commit()

            async with AsyncSession(bind=engine) as verify_session:
                appeals = (
                    (
                        await verify_session.execute(
                            select(DealAppeal).where(DealAppeal.deal_id == deal_id)
                        )
                    )
                    .scalars()
                    .all()
                )
                assert len(appeals) == 1
                await verify_session.execute(
                    delete(DealAppeal).where(DealAppeal.deal_id == deal_id)
                )
                await verify_session.execute(delete(Deal).where(Deal.id == deal_id))
                await verify_session.execute(
                    delete(UserWallet).where(UserWallet.account_id == u_id)
                )
                await verify_session.execute(
                    delete(MerchantWallet).where(MerchantWallet.account_id == m_id)
                )
                await verify_session.execute(delete(Account).where(Account.id.in_([u_id, m_id])))
                await verify_session.commit()
        finally:
            await s1.close()
            await s2.close()
            if tx1.is_active:
                await tx1.rollback()
            if tx2.is_active:
                await tx2.rollback()


@pytest.mark.asyncio
async def test_api_appeal_flow(
    client: AsyncClient,
    db_session: AsyncSession,
    make_account,
    make_wallet,
    make_merchant_wallet,
    make_deal,
):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("0"), frozen=Decimal("20"))

    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant, available=Decimal("0"))

    deal = await make_deal(
        merchant, status=DealStatus.ACCEPTED, user=user, amount_usdt=Decimal("20")
    )

    token = create_access_token(user.id, role=UserRole.USER)
    headers = {"Authorization": f"Bearer {token}"}

    response = await client.post(
        f"/appeals/deals/{deal.id}/appeal",
        json={
            "reason_code": "payment_not_received",
            "message": "Payment has not arrived yet",
        },
        headers=headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "open"

    appeal_id = data["id"]

    response_get = await client.get(f"/appeals/{appeal_id}", headers=headers)
    assert response_get.status_code == 200
    assert response_get.json()["id"] == appeal_id
