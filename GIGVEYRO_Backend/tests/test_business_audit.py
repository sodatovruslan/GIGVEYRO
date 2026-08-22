from decimal import Decimal

from sqlalchemy import select

from app.core.config import settings as app_settings
from app.core.security import create_access_token
from app.enums.account import UserRole
from app.enums.deal import DealStatus
from app.models.audit import AuditLog


def _auth_headers(account_id, role: UserRole) -> dict:
    token = create_access_token(account_id, role=role)
    return {"Authorization": f"Bearer {token}"}


async def _audit_records(db_session, entity_id, action):
    result = await db_session.execute(
        select(AuditLog).where(AuditLog.entity_id == str(entity_id), AuditLog.action == action)
    )
    return result.scalars().all()


async def test_appeal_open_creates_single_audit_record(
    client, db_session, make_account, make_wallet, make_merchant_wallet, make_deal
):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, frozen=Decimal("20"))
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant)
    deal = await make_deal(
        merchant, status=DealStatus.ACCEPTED, user=user, amount_usdt=Decimal("20")
    )

    response = await client.post(
        f"/appeals/deals/{deal.id}/appeal",
        json={"reason_code": "payment_not_received", "message": "Payment never arrived"},
        headers=_auth_headers(user.id, UserRole.USER),
    )
    assert response.status_code == 201
    appeal_id = response.json()["id"]

    records = await _audit_records(db_session, appeal_id, "appeal.open")
    assert len(records) == 1
    assert records[0].actor_account_id == user.id
    assert records[0].actor_role == "user"
    assert records[0].audit_metadata["deal_id"] == str(deal.id)


async def test_appeal_cancel_creates_single_audit_record(
    client, db_session, make_account, make_wallet, make_merchant_wallet, make_deal
):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, frozen=Decimal("20"))
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant)
    deal = await make_deal(
        merchant, status=DealStatus.ACCEPTED, user=user, amount_usdt=Decimal("20")
    )
    headers = _auth_headers(user.id, UserRole.USER)

    open_resp = await client.post(
        f"/appeals/deals/{deal.id}/appeal",
        json={"reason_code": "payment_not_received", "message": "Payment never arrived"},
        headers=headers,
    )
    appeal_id = open_resp.json()["id"]

    cancel_resp = await client.post(f"/appeals/{appeal_id}/cancel", headers=headers)
    assert cancel_resp.status_code == 200

    records = await _audit_records(db_session, appeal_id, "appeal.cancel")
    assert len(records) == 1
    assert records[0].actor_account_id == user.id


async def test_deposit_credited_creates_system_audit_record(
    client, db_session, make_account, make_wallet, make_deposit
):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user)
    owner = await make_account(role=UserRole.OWNER)
    deposit = await make_deposit(user, expected_amount=Decimal("60"), required_confirmations=1)

    response = await client.post(
        f"/owner/dev/deposits/{deposit.id}/simulate",
        json={
            "tx_hash": "tx-audit-credit-1",
            "amount": "60",
            "confirmations": 1,
            "network": "TRC20",
            "asset": "USDT",
            "destination_address": app_settings.USDT_TRC20_DEPOSIT_ADDRESS,
        },
        headers=_auth_headers(owner.id, UserRole.OWNER),
    )
    assert response.json()["status"] == "credited"

    records = await _audit_records(db_session, deposit.id, "deposit.credited")
    assert len(records) == 1
    assert records[0].actor_account_id is None
    assert records[0].actor_role == "system"


async def test_deposit_credit_replay_does_not_duplicate_audit(
    client, db_session, make_account, make_wallet, make_deposit
):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user)
    owner = await make_account(role=UserRole.OWNER)
    deposit = await make_deposit(user, expected_amount=Decimal("60"), required_confirmations=1)
    headers = _auth_headers(owner.id, UserRole.OWNER)
    payload = {
        "tx_hash": "tx-audit-replay-1",
        "amount": "60",
        "confirmations": 1,
        "network": "TRC20",
        "asset": "USDT",
        "destination_address": app_settings.USDT_TRC20_DEPOSIT_ADDRESS,
    }

    first = await client.post(
        f"/owner/dev/deposits/{deposit.id}/simulate", json=payload, headers=headers
    )
    second = await client.post(
        f"/owner/dev/deposits/{deposit.id}/simulate", json=payload, headers=headers
    )
    assert first.json()["status"] == "credited"
    assert second.json()["status"] == "credited"

    records = await _audit_records(db_session, deposit.id, "deposit.credited")
    assert len(records) == 1


async def test_deposit_amount_mismatch_creates_audit_record(
    client, db_session, make_account, make_wallet, make_deposit
):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user)
    owner = await make_account(role=UserRole.OWNER)
    deposit = await make_deposit(user, expected_amount=Decimal("100"), required_confirmations=1)

    response = await client.post(
        f"/owner/dev/deposits/{deposit.id}/simulate",
        json={
            "tx_hash": "tx-audit-mismatch-1",
            "amount": "50",
            "confirmations": 1,
            "network": "TRC20",
            "asset": "USDT",
            "destination_address": app_settings.USDT_TRC20_DEPOSIT_ADDRESS,
        },
        headers=_auth_headers(owner.id, UserRole.OWNER),
    )
    assert response.json()["status"] == "amount_mismatch"

    records = await _audit_records(db_session, deposit.id, "deposit.amount_mismatch")
    assert len(records) == 1
    assert records[0].actor_role == "system"
