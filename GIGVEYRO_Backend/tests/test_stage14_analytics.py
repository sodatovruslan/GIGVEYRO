from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.core.security import create_access_token
from app.enums.account import UserRole
from app.enums.deal import DealStatus
from app.enums.deposit import DepositStatus
from app.enums.wallet import Currency
from app.enums.withdrawal import WithdrawalDestinationType, WithdrawalStatus
from app.models.deal import Deal
from app.models.withdrawal import MerchantWithdrawal
from app.repositories.analytics import AnalyticsRepository
from app.services.analytics import OwnerAnalyticsService


@pytest.mark.asyncio
async def test_empty_database_analytics_safe_zeros(db_session):
    repo = AnalyticsRepository(db_session)
    service = OwnerAnalyticsService(repo)

    summary = await service.get_dashboard_summary()
    assert summary.accounts.users_total == 0
    assert summary.financials.total_completed_deal_volume_usdt == Decimal("0.00000000")
    assert summary.deals.total == 0
    assert summary.deposits.amount_credited_usdt == Decimal("0.00000000")

    deal_analytics = await service.get_deal_analytics()
    assert deal_analytics.total_deals == 0
    assert deal_analytics.completion_rate == Decimal("0.00")
    assert deal_analytics.total_volume_tjs == Decimal("0.00000000")


@pytest.mark.asyncio
async def test_owner_analytics_rbac_and_full_endpoints(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)

    owner_token = create_access_token(owner.id, role=UserRole.OWNER.value)
    user_token = create_access_token(user.id, role=UserRole.USER.value)

    ac = client
    user_res = await ac.get(
        "/api/v1/owner/dashboard/summary",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert user_res.status_code == 403

    owner_res = await ac.get(
        "/api/v1/owner/dashboard/summary",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert owner_res.status_code == 200
    data = owner_res.json()
    assert "accounts" in data
    assert "financials" in data

    deals_res = await ac.get(
        "/api/v1/owner/analytics/deals?period=30d",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert deals_res.status_code == 200

    top_m = await ac.get(
        "/api/v1/owner/analytics/top-merchants",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert top_m.status_code == 200

    top_u = await ac.get(
        "/api/v1/owner/analytics/top-users",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert top_u.status_code == 200


@pytest.mark.asyncio
async def test_analytics_aggregates_calculation(
    db_session, make_account, make_requisite, make_deposit, make_merchant_wallet
):
    user = await make_account(role=UserRole.USER)
    merchant = await make_account(role=UserRole.MERCHANT)
    req = await make_requisite(user)

    # Insert Completed Deal
    now = datetime.now(UTC)
    deal = Deal(
        public_id="DL-STAGE14-1",
        merchant_id=merchant.id,
        user_id=user.id,
        payment_requisite_id=req.id,
        amount_tjs=Decimal("1000.00000000"),
        amount_usdt=Decimal("100.00000000"),
        exchange_rate=Decimal("10.00000000"),
        status=DealStatus.COMPLETED,
        created_at=now - timedelta(hours=2),
        completed_at=now - timedelta(hours=1),
        expires_at=now + timedelta(hours=1),
    )
    db_session.add(deal)

    # Insert Credited Deposit
    deposit = await make_deposit(
        user, expected_amount=Decimal("500.00000000"), status=DepositStatus.CREDITED
    )
    deposit.credited_amount = Decimal("500.00000000")
    deposit.created_at = now - timedelta(hours=5)
    deposit.credited_at = now - timedelta(hours=4)

    # Insert Paid Withdrawal
    merchant_wallet = await make_merchant_wallet(merchant)
    withdrawal = MerchantWithdrawal(
        public_id="WD-STAGE14-1",
        merchant_id=merchant.id,
        merchant_wallet_id=merchant_wallet.id,
        destination_type=WithdrawalDestinationType.USDT_TRC20_ADDRESS,
        destination="TWithdrawTestAddr",
        amount=Decimal("200.00000000"),
        currency=Currency.USDT,
        status=WithdrawalStatus.PAID,
        created_by_account_id=merchant.id,
        created_at=now - timedelta(hours=3),
        paid_at=now - timedelta(hours=2),
    )
    db_session.add(withdrawal)
    await db_session.flush()

    repo = AnalyticsRepository(db_session)
    service = OwnerAnalyticsService(repo)

    summary = await service.get_dashboard_summary()
    assert summary.deals.completed == 1
    assert summary.deposits.credited == 1
    assert summary.withdrawals.paid == 1
    assert summary.financials.total_completed_deal_volume_tjs == Decimal("1000.00000000")
    assert summary.financials.total_completed_deal_volume_usdt == Decimal("100.00000000")
    assert summary.financials.total_credited_deposits_usdt == Decimal("500.00000000")
    assert summary.financials.total_paid_withdrawals_usdt == Decimal("200.00000000")
