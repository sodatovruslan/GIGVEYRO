from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.security import create_access_token
from app.enums.account import UserRole
from app.enums.notification import NotificationType
from app.enums.risk import RiskDecision, RiskReason, RiskStatus
from app.models.notification import Notification
from app.models.risk import RiskPolicy, TreasurySnapshotRecord
from app.repositories.risk import RiskRepository
from app.services.risk import RiskBlockedError, RiskDecisionService, RiskGuard, calculate_snapshot


def _policy(**overrides):
    values = dict(
        version=1,
        status="active",
        reserve_coverage_enabled=False,
        minimum_reserve_ratio_bps=10000,
        warning_reserve_ratio_bps=11000,
        max_treasury_data_age_seconds=300,
        single_deal_enabled=False,
        user_exposure_enabled=False,
        pending_withdrawals_enabled=False,
        total_open_deals_enabled=False,
        minimum_external_reserve_enabled=False,
    )
    values.update(overrides)
    return RiskPolicy(**values)


def _liabilities(user="100", merchant="50", frozen="20", pending="10", deals="20", profit="7"):
    return {
        key: Decimal(value)
        for key, value in {
            "user": user,
            "merchant": merchant,
            "frozen": frozen,
            "pending": pending,
            "open_deals": deals,
            "profit": profit,
        }.items()
    }


def test_treasury_snapshot_is_decimal_conservative_and_excludes_profit_usdc():
    now = datetime.now(UTC)
    result = calculate_snapshot(
        now=now,
        observed_at=now,
        provider_status="connected",
        external_usdt=Decimal("180"),
        external_usdc=Decimal("999"),
        liabilities=_liabilities(),
        policy=_policy(),
    )
    assert result.total_internal_liability_usdt == Decimal("150")
    assert result.required_reserve_usdt == Decimal("150.00000000")
    assert result.reserve_surplus_usdt == Decimal("30.00000000")
    assert result.coverage_ratio_bps == 12000
    assert result.risk_status == RiskStatus.HEALTHY
    assert result.owner_profit_usdt == Decimal("7.00000000")
    assert result.external_bybit_usdc == Decimal("999.00000000")


def test_zero_liability_stale_and_deficit_boundaries():
    now = datetime.now(UTC)
    zero = calculate_snapshot(
        now=now,
        observed_at=now,
        provider_status="connected",
        external_usdt=Decimal("0"),
        external_usdc=Decimal("0"),
        liabilities=_liabilities(
            user="0", merchant="0", frozen="0", pending="0", deals="0", profit="0"
        ),
        policy=_policy(),
    )
    assert zero.coverage_ratio_bps is None and zero.risk_status == RiskStatus.HEALTHY
    deficit = calculate_snapshot(
        now=now,
        observed_at=now,
        provider_status="connected",
        external_usdt=Decimal("149.99999999"),
        external_usdc=Decimal("0"),
        liabilities=_liabilities(),
        policy=_policy(),
    )
    assert deficit.risk_status == RiskStatus.CRITICAL and deficit.reserve_deficit_usdt > 0
    stale = calculate_snapshot(
        now=now,
        observed_at=now - timedelta(seconds=301),
        provider_status="connected",
        external_usdt=Decimal("1000"),
        external_usdc=Decimal("0"),
        liabilities=_liabilities(),
        policy=_policy(),
    )
    assert stale.risk_status == RiskStatus.STALE


def test_enforcement_disabled_allows_and_enabled_stale_or_deficit_blocks():
    now = datetime.now(UTC)
    stale = calculate_snapshot(
        now=now,
        observed_at=None,
        provider_status="unknown",
        external_usdt=Decimal("0"),
        external_usdc=Decimal("0"),
        liabilities=_liabilities(),
        policy=_policy(),
    )
    assert RiskDecisionService.reserve(stale, _policy()) == (RiskDecision.ALLOW, None)
    decision = RiskDecisionService.reserve(stale, _policy(reserve_coverage_enabled=True))
    assert decision == (RiskDecision.BLOCK, RiskReason.RESERVE_DATA_STALE)
    critical = calculate_snapshot(
        now=now,
        observed_at=now,
        provider_status="connected",
        external_usdt=Decimal("100"),
        external_usdc=Decimal("10000"),
        liabilities=_liabilities(),
        policy=_policy(reserve_coverage_enabled=True),
    )
    assert RiskDecisionService.reserve(critical, _policy(reserve_coverage_enabled=True)) == (
        RiskDecision.BLOCK,
        RiskReason.INSUFFICIENT_RESERVE,
    )


def _headers(account):
    return {"Authorization": f"Bearer {create_access_token(account.id, role=account.role)}"}


async def test_owner_risk_api_rbac_policy_preview_and_profit_separation(
    client, make_account, make_wallet, make_merchant_wallet
):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_wallet(user, available=Decimal("80"), insurance=Decimal("5"), frozen=Decimal("15"))
    await make_merchant_wallet(merchant, available=Decimal("40"))
    for actor in (user, merchant):
        assert (
            await client.get("/api/v1/owner/treasury/summary", headers=_headers(actor))
        ).status_code == 403
        assert (
            await client.get("/api/v1/owner/risk/policy", headers=_headers(actor))
        ).status_code == 403
    summary = await client.get("/api/v1/owner/treasury/summary", headers=_headers(owner))
    assert summary.status_code == 200
    assert Decimal(summary.json()["total_internal_liability_usdt"]) == Decimal("140")
    assert summary.json()["risk_status"] == "unknown"
    payload = {
        "reserve_coverage_enabled": True,
        "minimum_reserve_ratio_bps": 10000,
        "warning_reserve_ratio_bps": 11000,
        "max_treasury_data_age_seconds": 300,
        "single_deal_enabled": False,
        "user_exposure_enabled": False,
        "pending_withdrawals_enabled": False,
        "total_open_deals_enabled": False,
        "minimum_external_reserve_enabled": False,
    }
    preview = await client.post("/api/v1/owner/risk/preview", json=payload, headers=_headers(owner))
    assert preview.status_code == 200
    assert preview.json()["reserve_decision"] == "block"
    assert preview.json()["reason_code"] == "reserve_data_stale"
    created = await client.post(
        "/api/v1/owner/risk/policies", json=payload, headers=_headers(owner)
    )
    assert created.status_code == 201
    activated = await client.post(
        f"/api/v1/owner/risk/policies/{created.json()['id']}/activate", headers=_headers(owner)
    )
    assert activated.status_code == 200 and activated.json()["version"] == 2


async def test_treasury_refresh_notifies_owner_only_on_risk_transition(
    client, db_session, make_account, make_wallet, monkeypatch
):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("100"))

    async def critical_diagnostics():
        return {
            "status": "connected",
            "balances": [
                {
                    "asset": "USDT",
                    "available_balance": "0",
                    "wallet_balance": "0",
                    "received_at": datetime.now(UTC).isoformat(),
                }
            ],
        }

    monkeypatch.setattr(
        "app.api.owner.treasury.get_bybit_private_diagnostics", critical_diagnostics
    )
    for _ in range(2):
        response = await client.post(
            "/api/v1/owner/treasury/refresh", headers=_headers(owner)
        )
        assert response.status_code == 200
        assert response.json()["risk_status"] == "critical"

    count = await db_session.scalar(
        select(func.count(Notification.id)).where(
            Notification.account_id == owner.id,
            Notification.type == NotificationType.TREASURY_RISK_CHANGED,
        )
    )
    assert count == 1


async def test_enabled_guard_allows_healthy_and_blocks_limits_or_stale(
    db_session, make_account, make_wallet
):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("100"), frozen=Decimal("0"))
    policy = await RiskRepository(db_session).active_policy()
    policy.reserve_coverage_enabled = True
    policy.single_deal_enabled = True
    policy.max_single_deal_usdt = Decimal("20")
    db_session.add(
        TreasurySnapshotRecord(
            external_observed_at=datetime.now(UTC),
            provider_status="connected",
            external_bybit_usdt=Decimal("1000"),
            external_bybit_usdc=Decimal("5000"),
            internal_user_liability_usdt=Decimal("100"),
            merchant_liability_usdt=Decimal("0"),
            frozen_usdt=Decimal("0"),
            pending_withdrawal_usdt=Decimal("0"),
            open_deal_exposure_usdt=Decimal("0"),
            owner_profit_usdt=Decimal("999"),
            required_reserve_usdt=Decimal("100"),
            reserve_surplus_usdt=Decimal("900"),
            reserve_deficit_usdt=Decimal("0"),
            coverage_ratio_bps=100000,
            risk_status="healthy",
            policy_version=policy.version,
        )
    )
    await db_session.flush()
    guard = RiskGuard(RiskRepository(db_session))
    await guard.check_deal(user.id, Decimal("20"))
    with pytest.raises(RiskBlockedError) as limit:
        await guard.check_deal(user.id, Decimal("20.00000001"))
    assert limit.value.reason == RiskReason.SINGLE_DEAL_LIMIT
    policy.max_treasury_data_age_seconds = 30
    latest = await RiskRepository(db_session).latest_snapshot()
    latest.external_observed_at = datetime.now(UTC) - timedelta(seconds=31)
    await db_session.flush()
    with pytest.raises(RiskBlockedError) as stale:
        await guard.check_deal(user.id, Decimal("1"))
    assert stale.value.reason == RiskReason.RESERVE_DATA_STALE
