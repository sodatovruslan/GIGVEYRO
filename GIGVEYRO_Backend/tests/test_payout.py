from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.core.security import create_access_token
from app.enums.account import UserRole
from app.enums.notification import NotificationMessageKey
from app.enums.payout import PayoutSimulationOutcome, PayoutStatus
from app.enums.wallet import LedgerEntryType
from app.models.audit import AuditLog
from app.models.ledger import LedgerEntry
from app.models.notification import Notification
from app.models.payout import PayoutApproval, PayoutEvent, PayoutIntent
from app.models.risk import TreasurySnapshotRecord
from app.repositories.payout import PayoutRepository
from app.services.payout import PayoutSafetyError, transition_payout
from app.services.payout_runtime import build_controlled_payout_service


def _headers(account):
    return {"Authorization": f"Bearer {create_access_token(account.id, role=account.role)}"}


async def _enable_simulation(db_session, monkeypatch, *, dual_threshold=None):
    monkeypatch.setattr(settings, "PAYOUT_ENABLED", True)
    monkeypatch.setattr(settings, "PAYOUT_PROVIDER_MODE", "simulated")
    monkeypatch.setattr(settings, "PAYOUT_SIMULATION_ENABLED", True)
    policy = await PayoutRepository(db_session).active_policy()
    policy.payouts_enabled = True
    policy.dual_approval_threshold_usdt = dual_threshold
    db_session.add(
        TreasurySnapshotRecord(
            external_observed_at=datetime.now(UTC),
            provider_status="connected",
            external_bybit_usdt=Decimal("100000"),
            external_bybit_usdc=Decimal("0"),
            internal_user_liability_usdt=Decimal("0"),
            merchant_liability_usdt=Decimal("0"),
            frozen_usdt=Decimal("0"),
            pending_withdrawal_usdt=Decimal("0"),
            open_deal_exposure_usdt=Decimal("0"),
            owner_profit_usdt=Decimal("0"),
            required_reserve_usdt=Decimal("0"),
            reserve_surplus_usdt=Decimal("100000"),
            reserve_deficit_usdt=Decimal("0"),
            coverage_ratio_bps=None,
            risk_status="healthy",
            policy_version=1,
        )
    )
    await db_session.flush()


async def _withdrawal(client, merchant, amount="25"):
    response = await client.post(
        "/merchant/withdrawals",
        json={
            "amount": amount,
            "destination_type": "usdt_trc20_address",
            "destination": "T" * 34,
        },
        headers=_headers(merchant),
    )
    assert response.status_code == 201
    return response.json()


async def _intent(client, owner):
    response = await client.get("/api/v1/owner/payouts", headers=_headers(owner))
    assert response.status_code == 200
    return response.json()["items"][0]


def test_payout_state_machine_rejects_arbitrary_jumps():
    intent = PayoutIntent(status=PayoutStatus.REQUESTED.value)
    transition_payout(intent, PayoutStatus.RISK_REVIEW)
    assert intent.status == PayoutStatus.RISK_REVIEW.value
    with pytest.raises(Exception, match="cannot transition"):
        transition_payout(intent, PayoutStatus.SUCCEEDED)


async def test_payout_defaults_are_disabled_and_live_execute_endpoint_is_blocked(
    client, db_session, make_account, make_merchant_wallet
):
    merchant = await make_account(role=UserRole.MERCHANT)
    owner = await make_account(role=UserRole.OWNER)
    await make_merchant_wallet(merchant, available=Decimal("100"))
    await _withdrawal(client, merchant)
    intent = await _intent(client, owner)
    owner_notification = await db_session.scalar(
        select(Notification).where(Notification.account_id == owner.id)
    )
    assert owner_notification.message_key == NotificationMessageKey.PAYOUT_APPROVAL_REQUIRED
    assert intent["provider_mode"] == "disabled"
    assert intent["status"] == "risk_review"
    response = await client.post(
        f"/api/v1/owner/payouts/{intent['id']}/execute", headers=_headers(owner)
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "LIVE_PAYOUT_NOT_AVAILABLE"


async def test_simulated_success_is_exactly_once_and_finalizes_existing_hold(
    client, db_session, make_account, make_merchant_wallet, monkeypatch
):
    merchant = await make_account(role=UserRole.MERCHANT)
    owner = await make_account(role=UserRole.OWNER)
    wallet = await make_merchant_wallet(merchant, available=Decimal("100"))
    await _enable_simulation(db_session, monkeypatch)
    withdrawal = await _withdrawal(client, merchant, "40")
    intent = await _intent(client, owner)
    assert (
        await client.post(f"/api/v1/owner/payouts/{intent['id']}/approve", headers=_headers(owner))
    ).status_code == 200
    assert (
        await client.post(
            f"/api/v1/owner/payouts/{intent['id']}/queue",
            json={"outcome": "succeeded"},
            headers=_headers(owner),
        )
    ).status_code == 200
    service = build_controlled_payout_service(db_session)
    result = await service.execute(intent["id"])
    assert result.status == "succeeded"
    retry = await service.execute(intent["id"])
    assert retry.status == "succeeded"
    await db_session.refresh(wallet)
    assert wallet.available_balance == Decimal("60")
    assert wallet.held_balance == Decimal("0")
    paid = await db_session.scalar(
        select(func.count())
        .select_from(LedgerEntry)
        .where(
            LedgerEntry.reference_id == withdrawal["id"],
            LedgerEntry.type == LedgerEntryType.WITHDRAWAL_PAID,
        )
    )
    assert paid == 1
    assert await db_session.scalar(select(func.count()).select_from(PayoutIntent)) == 1
    assert await db_session.scalar(select(func.count()).select_from(PayoutApproval)) == 1
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "payout.simulated_succeeded")
        )
        == 1
    )
    merchant_notifications = (
        await db_session.scalars(
            select(Notification).where(
                Notification.account_id == merchant.id,
                Notification.type == "WITHDRAWAL_STATUS_CHANGED",
            )
        )
    ).all()
    assert {item.message_key for item in merchant_notifications} == {
        NotificationMessageKey.WITHDRAWAL_APPROVED,
        NotificationMessageKey.WITHDRAWAL_COMPLETED,
    }


async def test_unknown_result_never_retries_and_requires_reconciliation(
    client, db_session, make_account, make_merchant_wallet, monkeypatch
):
    merchant = await make_account(role=UserRole.MERCHANT)
    owner = await make_account(role=UserRole.OWNER)
    wallet = await make_merchant_wallet(merchant, available=Decimal("100"))
    await _enable_simulation(db_session, monkeypatch)
    await _withdrawal(client, merchant, "30")
    intent = await _intent(client, owner)
    await client.post(f"/api/v1/owner/payouts/{intent['id']}/approve", headers=_headers(owner))
    await client.post(
        f"/api/v1/owner/payouts/{intent['id']}/queue",
        json={"outcome": "unknown"},
        headers=_headers(owner),
    )
    service = build_controlled_payout_service(db_session)
    unknown = await service.execute(intent["id"])
    assert unknown.status == "reconciliation_required"
    await db_session.refresh(wallet)
    assert wallet.held_balance == Decimal("30")
    retry = await service.execute(intent["id"])
    assert retry.status == "reconciliation_required"
    reconciled = await service.reconcile(intent["id"], owner, PayoutSimulationOutcome.SUCCEEDED)
    assert reconciled.status == "succeeded"
    await db_session.refresh(wallet)
    assert wallet.held_balance == Decimal("0")
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(PayoutEvent)
            .where(PayoutEvent.event == "payout.reconciliation_required")
        )
        == 1
    )


async def test_pending_result_is_not_selected_for_blind_retry(
    client, db_session, make_account, make_merchant_wallet, monkeypatch
):
    merchant = await make_account(role=UserRole.MERCHANT)
    owner = await make_account(role=UserRole.OWNER)
    wallet = await make_merchant_wallet(merchant, available=Decimal("100"))
    await _enable_simulation(db_session, monkeypatch)
    await _withdrawal(client, merchant, "15")
    intent = await _intent(client, owner)
    await client.post(f"/api/v1/owner/payouts/{intent['id']}/approve", headers=_headers(owner))
    await client.post(
        f"/api/v1/owner/payouts/{intent['id']}/queue",
        json={"outcome": "pending"},
        headers=_headers(owner),
    )

    service = build_controlled_payout_service(db_session)
    pending = await service.execute(intent["id"])
    assert pending.status == PayoutStatus.RECONCILIATION_REQUIRED
    assert pending.failure_code == "PROVIDER_PENDING"
    assert await PayoutRepository(db_session).next_queued() == []
    await db_session.refresh(wallet)
    assert wallet.held_balance == Decimal("15")

    still_pending = await service.reconcile(intent["id"], owner, PayoutSimulationOutcome.PENDING)
    assert still_pending.status == PayoutStatus.RECONCILIATION_REQUIRED
    await db_session.refresh(wallet)
    assert wallet.held_balance == Decimal("15")


async def test_manual_settlement_requires_evidence_and_is_exactly_once(
    client, db_session, make_account, make_merchant_wallet, monkeypatch
):
    merchant = await make_account(role=UserRole.MERCHANT)
    owner = await make_account(role=UserRole.OWNER)
    wallet = await make_merchant_wallet(merchant, available=Decimal("100"))
    await _enable_simulation(db_session, monkeypatch)
    withdrawal = await _withdrawal(client, merchant, "22")
    intent = await _intent(client, owner)
    await client.post(f"/api/v1/owner/payouts/{intent['id']}/approve", headers=_headers(owner))

    started = await client.post(
        f"/api/v1/owner/payouts/{intent['id']}/manual", headers=_headers(owner)
    )
    assert started.status_code == 200
    assert started.json()["status"] == PayoutStatus.AWAITING_MANUAL_SETTLEMENT
    invalid = await client.post(
        f"/api/v1/owner/payouts/{intent['id']}/manual/complete",
        json={"external_reference": "", "evidence": ""},
        headers=_headers(owner),
    )
    assert invalid.status_code == 422
    completed = await client.post(
        f"/api/v1/owner/payouts/{intent['id']}/manual/complete",
        json={"external_reference": "MANUAL-REFERENCE-001", "evidence": "ticket:42"},
        headers=_headers(owner),
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == PayoutStatus.SUCCEEDED
    retry = await client.post(
        f"/api/v1/owner/payouts/{intent['id']}/manual/complete",
        json={"external_reference": "MANUAL-REFERENCE-001", "evidence": "ticket:42"},
        headers=_headers(owner),
    )
    assert retry.status_code == 200
    await db_session.refresh(wallet)
    assert wallet.held_balance == Decimal("0")
    paid = await db_session.scalar(
        select(func.count())
        .select_from(LedgerEntry)
        .where(
            LedgerEntry.reference_id == withdrawal["id"],
            LedgerEntry.type == LedgerEntryType.WITHDRAWAL_PAID,
        )
    )
    assert paid == 1


async def test_intent_tampering_blocks_control_actions(
    client, db_session, make_account, make_merchant_wallet, monkeypatch
):
    merchant = await make_account(role=UserRole.MERCHANT)
    owner = await make_account(role=UserRole.OWNER)
    await make_merchant_wallet(merchant, available=Decimal("100"))
    await _enable_simulation(db_session, monkeypatch)
    await _withdrawal(client, merchant, "12")
    intent_data = await _intent(client, owner)
    intent = await PayoutRepository(db_session).get(intent_data["id"], lock=True)
    assert intent is not None
    intent.amount = Decimal("13")

    with pytest.raises(PayoutSafetyError, match="PAYOUT_INTENT_CHANGED"):
        await build_controlled_payout_service(db_session).cancel(intent.id, owner)


async def test_simulated_failure_is_terminal_and_preserves_hold(
    client, db_session, make_account, make_merchant_wallet, monkeypatch
):
    merchant = await make_account(role=UserRole.MERCHANT)
    owner = await make_account(role=UserRole.OWNER)
    wallet = await make_merchant_wallet(merchant, available=Decimal("100"))
    await _enable_simulation(db_session, monkeypatch)
    await _withdrawal(client, merchant, "18")
    intent = await _intent(client, owner)
    await client.post(f"/api/v1/owner/payouts/{intent['id']}/approve", headers=_headers(owner))
    await client.post(
        f"/api/v1/owner/payouts/{intent['id']}/queue",
        json={"outcome": "failed"},
        headers=_headers(owner),
    )

    result = await build_controlled_payout_service(db_session).execute(intent["id"])
    assert result.status == PayoutStatus.FAILED
    assert result.failure_kind == "permanent_failure"
    await db_session.refresh(wallet)
    assert wallet.held_balance == Decimal("18")
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(LedgerEntry)
            .where(LedgerEntry.reference_id == intent["withdrawal_id"])
        )
        == 1
    )


async def test_payout_limit_and_stale_execution_snapshot_block_safely(
    client, db_session, make_account, make_merchant_wallet, monkeypatch
):
    merchant = await make_account(role=UserRole.MERCHANT)
    owner = await make_account(role=UserRole.OWNER)
    wallet = await make_merchant_wallet(merchant, available=Decimal("100"))
    await _enable_simulation(db_session, monkeypatch)
    policy = await PayoutRepository(db_session).active_policy()
    policy.max_single_payout_enabled = True
    policy.max_single_payout_usdt = Decimal("10")
    await _withdrawal(client, merchant, "20")
    intent = await _intent(client, owner)
    blocked = await client.post(
        f"/api/v1/owner/payouts/{intent['id']}/approve", headers=_headers(owner)
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "MAX_SINGLE_PAYOUT"

    policy.max_single_payout_enabled = False
    approved = await client.post(
        f"/api/v1/owner/payouts/{intent['id']}/approve", headers=_headers(owner)
    )
    assert approved.status_code == 200
    await client.post(
        f"/api/v1/owner/payouts/{intent['id']}/queue",
        json={"outcome": "succeeded"},
        headers=_headers(owner),
    )
    latest = (
        (
            await db_session.execute(
                select(TreasurySnapshotRecord).order_by(TreasurySnapshotRecord.generated_at.desc())
            )
        )
        .scalars()
        .first()
    )
    assert latest is not None
    latest.external_observed_at = datetime.now(UTC) - timedelta(days=1)

    with pytest.raises(PayoutSafetyError, match="reserve_data_stale"):
        await build_controlled_payout_service(db_session).execute(intent["id"])
    stored = await PayoutRepository(db_session).get(intent["id"])
    assert stored is not None and stored.status == PayoutStatus.QUEUED
    await db_session.refresh(wallet)
    assert wallet.held_balance == Decimal("20")


async def test_dual_control_requires_distinct_owners(
    client, db_session, make_account, make_merchant_wallet, monkeypatch
):
    merchant = await make_account(role=UserRole.MERCHANT)
    owner_one = await make_account(role=UserRole.OWNER)
    owner_two = await make_account(role=UserRole.OWNER)
    await make_merchant_wallet(merchant, available=Decimal("100"))
    await _enable_simulation(db_session, monkeypatch, dual_threshold=Decimal("10"))
    await _withdrawal(client, merchant, "20")
    intent = await _intent(client, owner_one)
    assert intent["required_approvals"] == 2
    first = await client.post(
        f"/api/v1/owner/payouts/{intent['id']}/approve", headers=_headers(owner_one)
    )
    assert first.json()["status"] == "risk_review"
    duplicate = await client.post(
        f"/api/v1/owner/payouts/{intent['id']}/approve", headers=_headers(owner_one)
    )
    assert duplicate.json()["approval_count"] == 1
    second = await client.post(
        f"/api/v1/owner/payouts/{intent['id']}/approve", headers=_headers(owner_two)
    )
    assert second.json()["status"] == "approved"
    assert second.json()["approval_count"] == 2


async def test_kill_switch_and_rbac_block_execution_controls(
    client, db_session, make_account, make_merchant_wallet, monkeypatch
):
    merchant = await make_account(role=UserRole.MERCHANT)
    owner = await make_account(role=UserRole.OWNER)
    await make_merchant_wallet(merchant, available=Decimal("100"))
    await _enable_simulation(db_session, monkeypatch)
    await _withdrawal(client, merchant)
    intent = await _intent(client, owner)
    assert (
        await client.get("/api/v1/owner/payouts", headers=_headers(merchant))
    ).status_code == 403
    await client.post(f"/api/v1/owner/payouts/{intent['id']}/approve", headers=_headers(owner))
    monkeypatch.setattr(settings, "PAYOUT_ENABLED", False)
    blocked = await client.post(
        f"/api/v1/owner/payouts/{intent['id']}/queue",
        json={"outcome": "succeeded"},
        headers=_headers(owner),
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "PAYOUT_ENABLED_FALSE"
    monkeypatch.setattr(settings, "PAYOUT_ENABLED", True)
    queued = await client.post(
        f"/api/v1/owner/payouts/{intent['id']}/queue",
        json={"outcome": "succeeded"},
        headers=_headers(owner),
    )
    assert queued.status_code == 200
    monkeypatch.setattr(settings, "PAYOUT_ENABLED", False)
    with pytest.raises(PayoutSafetyError, match="PAYOUT_ENABLED_FALSE"):
        await build_controlled_payout_service(db_session).execute(intent["id"])
