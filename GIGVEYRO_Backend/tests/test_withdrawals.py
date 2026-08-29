from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.enums.account import UserRole
from app.enums.wallet import LedgerEntryType
from app.models.ledger import LedgerEntry
from app.models.merchant_wallet import MerchantWallet


def _auth_headers(account_id, role: UserRole) -> dict:
    token = create_access_token(account_id, role=role)
    return {"Authorization": f"Bearer {token}"}


async def _wallet(db_session: AsyncSession, account_id) -> MerchantWallet:
    result = await db_session.execute(
        select(MerchantWallet).where(MerchantWallet.account_id == account_id)
    )
    return result.scalar_one()


@pytest.mark.asyncio
async def test_create_withdrawal_holds_balance(
    client: AsyncClient, db_session: AsyncSession, make_account, make_merchant_wallet
):
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant, available=Decimal("100"))

    response = await client.post(
        "/merchant/withdrawals",
        json={
            "amount": "40",
            "destination_type": "usdt_trc20_address",
            "destination": "T" * 34,
        },
        headers=_auth_headers(merchant.id, UserRole.MERCHANT),
    )
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "pending"

    wallet = await _wallet(db_session, merchant.id)
    assert wallet.available_balance == Decimal("60")
    assert wallet.held_balance == Decimal("40")


@pytest.mark.asyncio
async def test_create_withdrawal_insufficient_balance(
    client: AsyncClient, make_account, make_merchant_wallet
):
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant, available=Decimal("10"))

    response = await client.post(
        "/merchant/withdrawals",
        json={
            "amount": "40",
            "destination_type": "usdt_trc20_address",
            "destination": "T" * 34,
        },
        headers=_auth_headers(merchant.id, UserRole.MERCHANT),
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_create_withdrawal_invalid_trc20_address(
    client: AsyncClient, make_account, make_merchant_wallet
):
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant, available=Decimal("100"))

    response = await client.post(
        "/merchant/withdrawals",
        json={
            "amount": "40",
            "destination_type": "usdt_trc20_address",
            "destination": "tooshort",
        },
        headers=_auth_headers(merchant.id, UserRole.MERCHANT),
    )
    assert response.status_code == 400
    assert "invalid TRC20 address length" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_withdrawal_forbidden_for_user_role(
    client: AsyncClient, make_account, make_wallet
):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("100"))

    response = await client.post(
        "/merchant/withdrawals",
        json={
            "amount": "10",
            "destination_type": "usdt_trc20_address",
            "destination": "T" * 34,
        },
        headers=_auth_headers(user.id, UserRole.USER),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_cancel_by_merchant_releases_hold_and_is_idempotent(
    client: AsyncClient, db_session: AsyncSession, make_account, make_merchant_wallet
):
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant, available=Decimal("100"))
    headers = _auth_headers(merchant.id, UserRole.MERCHANT)

    create_resp = await client.post(
        "/merchant/withdrawals",
        json={
            "amount": "30",
            "destination_type": "usdt_trc20_address",
            "destination": "T" * 34,
        },
        headers=headers,
    )
    withdrawal_id = create_resp.json()["id"]

    cancel_resp = await client.post(
        f"/merchant/withdrawals/{withdrawal_id}/cancel", headers=headers
    )
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "cancelled"

    wallet = await _wallet(db_session, merchant.id)
    assert wallet.available_balance == Decimal("100")
    assert wallet.held_balance == Decimal("0")

    # idempotent: cancelling an already-cancelled withdrawal is a no-op, not an error
    second_cancel = await client.post(
        f"/merchant/withdrawals/{withdrawal_id}/cancel", headers=headers
    )
    assert second_cancel.status_code == 200
    assert second_cancel.json()["status"] == "cancelled"

    wallet_after = await _wallet(db_session, merchant.id)
    assert wallet_after.available_balance == Decimal("100")
    assert wallet_after.held_balance == Decimal("0")


@pytest.mark.asyncio
async def test_cannot_cancel_already_approved_withdrawal(
    client: AsyncClient, make_account, make_merchant_wallet
):
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant, available=Decimal("100"))
    owner = await make_account(role=UserRole.OWNER)

    create_resp = await client.post(
        "/merchant/withdrawals",
        json={
            "amount": "20",
            "destination_type": "usdt_trc20_address",
            "destination": "T" * 34,
        },
        headers=_auth_headers(merchant.id, UserRole.MERCHANT),
    )
    withdrawal_id = create_resp.json()["id"]

    approve_resp = await client.post(
        f"/owner/withdrawals/{withdrawal_id}/approve",
        headers=_auth_headers(owner.id, UserRole.OWNER),
    )
    assert approve_resp.status_code == 200

    cancel_resp = await client.post(
        f"/merchant/withdrawals/{withdrawal_id}/cancel",
        headers=_auth_headers(merchant.id, UserRole.MERCHANT),
    )
    assert cancel_resp.status_code == 400


@pytest.mark.asyncio
async def test_direct_mark_paid_is_blocked_and_does_not_debit_hold(
    client: AsyncClient, db_session: AsyncSession, make_account, make_merchant_wallet
):
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant, available=Decimal("100"))
    owner = await make_account(role=UserRole.OWNER)
    owner_headers = _auth_headers(owner.id, UserRole.OWNER)

    create_resp = await client.post(
        "/merchant/withdrawals",
        json={
            "amount": "50",
            "destination_type": "usdt_trc20_address",
            "destination": "T" * 34,
        },
        headers=_auth_headers(merchant.id, UserRole.MERCHANT),
    )
    withdrawal_id = create_resp.json()["id"]

    approve_resp = await client.post(
        f"/owner/withdrawals/{withdrawal_id}/approve",
        json={"comment": "looks fine"},
        headers=owner_headers,
    )
    assert approve_resp.status_code == 200
    assert approve_resp.json()["status"] == "approved"

    wallet_after_approve = await _wallet(db_session, merchant.id)
    assert wallet_after_approve.available_balance == Decimal("50")
    assert wallet_after_approve.held_balance == Decimal("50")

    paid_resp = await client.post(
        f"/owner/withdrawals/{withdrawal_id}/mark-paid", headers=owner_headers
    )
    assert paid_resp.status_code == 409
    assert paid_resp.json()["detail"]["code"] == "CONTROLLED_PAYOUT_REQUIRED"

    wallet_after_paid = await _wallet(db_session, merchant.id)
    assert wallet_after_paid.available_balance == Decimal("50")
    assert wallet_after_paid.held_balance == Decimal("50")

    ledger_entries = (
        (
            await db_session.execute(
                select(LedgerEntry).where(LedgerEntry.reference_id == withdrawal_id)
            )
        )
        .scalars()
        .all()
    )
    entry_types = {entry.type for entry in ledger_entries}
    assert entry_types == {LedgerEntryType.WITHDRAWAL_HOLD}

    # Retries cannot bypass controlled payout or create a paid ledger entry.
    await client.post(f"/owner/withdrawals/{withdrawal_id}/approve", headers=owner_headers)
    await client.post(f"/owner/withdrawals/{withdrawal_id}/mark-paid", headers=owner_headers)

    ledger_entries_after_retry = (
        (
            await db_session.execute(
                select(LedgerEntry).where(LedgerEntry.reference_id == withdrawal_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(ledger_entries_after_retry) == len(ledger_entries)

    wallet_final = await _wallet(db_session, merchant.id)
    assert wallet_final.held_balance == Decimal("50")


@pytest.mark.asyncio
async def test_owner_reject_releases_held_balance(
    client: AsyncClient, db_session: AsyncSession, make_account, make_merchant_wallet
):
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant, available=Decimal("100"))
    owner = await make_account(role=UserRole.OWNER)
    owner_headers = _auth_headers(owner.id, UserRole.OWNER)

    create_resp = await client.post(
        "/merchant/withdrawals",
        json={
            "amount": "35",
            "destination_type": "bybit_uid",
            "destination": "123456789",
        },
        headers=_auth_headers(merchant.id, UserRole.MERCHANT),
    )
    withdrawal_id = create_resp.json()["id"]

    reject_resp = await client.post(
        f"/owner/withdrawals/{withdrawal_id}/reject",
        json={"comment": "invalid destination"},
        headers=owner_headers,
    )
    assert reject_resp.status_code == 200
    assert reject_resp.json()["status"] == "rejected"

    wallet = await _wallet(db_session, merchant.id)
    assert wallet.available_balance == Decimal("100")
    assert wallet.held_balance == Decimal("0")

    # idempotent double-reject: no extra release entries, balance stays correct
    second_reject = await client.post(
        f"/owner/withdrawals/{withdrawal_id}/reject", headers=owner_headers
    )
    assert second_reject.status_code == 200

    wallet_after = await _wallet(db_session, merchant.id)
    assert wallet_after.available_balance == Decimal("100")
    assert wallet_after.held_balance == Decimal("0")


@pytest.mark.asyncio
async def test_cannot_approve_non_pending_withdrawal(
    client: AsyncClient, make_account, make_merchant_wallet
):
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant, available=Decimal("100"))
    owner = await make_account(role=UserRole.OWNER)
    owner_headers = _auth_headers(owner.id, UserRole.OWNER)

    create_resp = await client.post(
        "/merchant/withdrawals",
        json={
            "amount": "10",
            "destination_type": "usdt_trc20_address",
            "destination": "T" * 34,
        },
        headers=_auth_headers(merchant.id, UserRole.MERCHANT),
    )
    withdrawal_id = create_resp.json()["id"]

    reject_resp = await client.post(
        f"/owner/withdrawals/{withdrawal_id}/reject", headers=owner_headers
    )
    assert reject_resp.status_code == 200

    approve_resp = await client.post(
        f"/owner/withdrawals/{withdrawal_id}/approve", headers=owner_headers
    )
    assert approve_resp.status_code == 400


@pytest.mark.asyncio
async def test_merchant_cannot_access_owner_withdrawal_endpoints(
    client: AsyncClient, make_account, make_merchant_wallet
):
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant, available=Decimal("100"))

    response = await client.get(
        "/owner/withdrawals", headers=_auth_headers(merchant.id, UserRole.MERCHANT)
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_merchant_cannot_view_another_merchants_withdrawal(
    client: AsyncClient, make_account, make_merchant_wallet
):
    merchant_a = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant_a, available=Decimal("100"))
    merchant_b = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant_b, available=Decimal("50"))

    create_resp = await client.post(
        "/merchant/withdrawals",
        json={
            "amount": "10",
            "destination_type": "usdt_trc20_address",
            "destination": "T" * 34,
        },
        headers=_auth_headers(merchant_a.id, UserRole.MERCHANT),
    )
    withdrawal_id = create_resp.json()["id"]

    response = await client.get(
        f"/merchant/withdrawals/{withdrawal_id}",
        headers=_auth_headers(merchant_b.id, UserRole.MERCHANT),
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_owner_list_filters_by_merchant_and_status(
    client: AsyncClient, make_account, make_merchant_wallet
):
    merchant_a = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant_a, available=Decimal("100"))
    merchant_b = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant_b, available=Decimal("100"))
    owner = await make_account(role=UserRole.OWNER)

    await client.post(
        "/merchant/withdrawals",
        json={"amount": "10", "destination_type": "usdt_trc20_address", "destination": "T" * 34},
        headers=_auth_headers(merchant_a.id, UserRole.MERCHANT),
    )
    await client.post(
        "/merchant/withdrawals",
        json={"amount": "15", "destination_type": "usdt_trc20_address", "destination": "T" * 34},
        headers=_auth_headers(merchant_b.id, UserRole.MERCHANT),
    )

    response = await client.get(
        f"/owner/withdrawals?merchant_id={merchant_a.id}",
        headers=_auth_headers(owner.id, UserRole.OWNER),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["merchant_id"] == str(merchant_a.id)
