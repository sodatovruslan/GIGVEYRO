from decimal import Decimal

from app.core.security import create_access_token
from app.enums.account import UserRole


def _auth_headers(account) -> dict:
    token = create_access_token(account.id, account.role.value)
    return {"Authorization": f"Bearer {token}"}


async def test_user_creates_withdrawal(client, make_account, make_wallet):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("100"))

    response = await client.post(
        "/withdrawals",
        json={
            "amount": "40",
            "destination_type": "usdt_trc20_address",
            "destination": "T" + "a" * 33,
        },
        headers=_auth_headers(user),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending"
    assert body["amount"] == "40.00000000"
    assert body["public_id"].startswith("UWD-")


async def test_withdrawal_holds_funds_from_available_balance(client, make_account, make_wallet):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("100"))

    await client.post(
        "/withdrawals",
        json={
            "amount": "40",
            "destination_type": "usdt_trc20_address",
            "destination": "T" + "a" * 33,
        },
        headers=_auth_headers(user),
    )

    wallet_response = await client.get("/wallet", headers=_auth_headers(user))
    assert wallet_response.json()["available_balance"] == "60.00000000"
    assert wallet_response.json()["frozen_balance"] == "40.00000000"


async def test_withdrawal_rejects_insufficient_balance(client, make_account, make_wallet):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("10"))

    response = await client.post(
        "/withdrawals",
        json={
            "amount": "40",
            "destination_type": "usdt_trc20_address",
            "destination": "T" + "a" * 33,
        },
        headers=_auth_headers(user),
    )

    assert response.status_code == 400


async def test_merchant_cannot_create_user_withdrawal(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.post(
        "/withdrawals",
        json={
            "amount": "40",
            "destination_type": "usdt_trc20_address",
            "destination": "T" + "a" * 33,
        },
        headers=_auth_headers(merchant),
    )

    assert response.status_code == 403


async def test_user_cannot_see_another_users_withdrawal(client, make_account, make_wallet):
    user_a = await make_account(role=UserRole.USER)
    user_b = await make_account(role=UserRole.USER)
    await make_wallet(user_a, available=Decimal("100"))

    create = await client.post(
        "/withdrawals",
        json={
            "amount": "10",
            "destination_type": "usdt_trc20_address",
            "destination": "T" + "a" * 33,
        },
        headers=_auth_headers(user_a),
    )
    withdrawal_id = create.json()["id"]

    response = await client.get(
        f"/withdrawals/{withdrawal_id}", headers=_auth_headers(user_b)
    )

    assert response.status_code == 404


async def test_user_cancels_pending_withdrawal_and_funds_released(
    client, make_account, make_wallet
):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("100"))
    create = await client.post(
        "/withdrawals",
        json={
            "amount": "30",
            "destination_type": "usdt_trc20_address",
            "destination": "T" + "a" * 33,
        },
        headers=_auth_headers(user),
    )
    withdrawal_id = create.json()["id"]

    cancel = await client.post(
        f"/withdrawals/{withdrawal_id}/cancel", headers=_auth_headers(user)
    )
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"

    wallet_response = await client.get("/wallet", headers=_auth_headers(user))
    assert wallet_response.json()["available_balance"] == "100.00000000"
    assert wallet_response.json()["frozen_balance"] == "0.00000000"


async def test_owner_approves_and_rejects_user_withdrawal(client, make_account, make_wallet):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("100"))
    owner = await make_account(role=UserRole.OWNER)
    create = await client.post(
        "/withdrawals",
        json={
            "amount": "20",
            "destination_type": "usdt_trc20_address",
            "destination": "T" + "a" * 33,
        },
        headers=_auth_headers(user),
    )
    withdrawal_id = create.json()["id"]

    approve = await client.post(
        f"/owner/user-withdrawals/{withdrawal_id}/approve", headers=_auth_headers(owner)
    )
    assert approve.status_code == 200
    assert approve.json()["status"] == "approved"

    # Can't reject once approved.
    reject_after_approve = await client.post(
        f"/owner/user-withdrawals/{withdrawal_id}/reject", headers=_auth_headers(owner)
    )
    assert reject_after_approve.status_code == 400


async def test_owner_rejects_user_withdrawal_and_releases_funds(
    client, make_account, make_wallet
):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("100"))
    owner = await make_account(role=UserRole.OWNER)
    create = await client.post(
        "/withdrawals",
        json={
            "amount": "20",
            "destination_type": "usdt_trc20_address",
            "destination": "T" + "a" * 33,
        },
        headers=_auth_headers(user),
    )
    withdrawal_id = create.json()["id"]

    reject = await client.post(
        f"/owner/user-withdrawals/{withdrawal_id}/reject", headers=_auth_headers(owner)
    )
    assert reject.status_code == 200
    assert reject.json()["status"] == "rejected"

    wallet_response = await client.get("/wallet", headers=_auth_headers(user))
    assert wallet_response.json()["available_balance"] == "100.00000000"


async def test_mark_paid_is_disabled_for_user_withdrawals(client, make_account, make_wallet):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("100"))
    owner = await make_account(role=UserRole.OWNER)
    create = await client.post(
        "/withdrawals",
        json={
            "amount": "20",
            "destination_type": "usdt_trc20_address",
            "destination": "T" + "a" * 33,
        },
        headers=_auth_headers(user),
    )
    withdrawal_id = create.json()["id"]
    await client.post(
        f"/owner/user-withdrawals/{withdrawal_id}/approve", headers=_auth_headers(owner)
    )

    response = await client.post(
        f"/owner/user-withdrawals/{withdrawal_id}/mark-paid", headers=_auth_headers(owner)
    )

    assert response.status_code == 409


async def test_owner_lists_all_user_withdrawals(client, make_account, make_wallet):
    user_a = await make_account(role=UserRole.USER)
    user_b = await make_account(role=UserRole.USER)
    await make_wallet(user_a, available=Decimal("50"))
    await make_wallet(user_b, available=Decimal("50"))
    owner = await make_account(role=UserRole.OWNER)

    await client.post(
        "/withdrawals",
        json={
            "amount": "10",
            "destination_type": "usdt_trc20_address",
            "destination": "T" + "a" * 33,
        },
        headers=_auth_headers(user_a),
    )
    await client.post(
        "/withdrawals",
        json={
            "amount": "15",
            "destination_type": "usdt_trc20_address",
            "destination": "T" + "a" * 33,
        },
        headers=_auth_headers(user_b),
    )

    response = await client.get("/owner/user-withdrawals", headers=_auth_headers(owner))

    assert response.status_code == 200
    assert response.json()["total"] == 2
