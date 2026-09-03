import uuid
from decimal import Decimal

from app.core.security import create_access_token
from app.enums.account import UserRole
from app.enums.deposit import DepositStatus


def _auth_headers(account) -> dict:
    token = create_access_token(account.id, account.role.value)
    return {"Authorization": f"Bearer {token}"}


async def test_owner_lists_all_deposits(client, make_account, make_deposit):
    owner = await make_account(role=UserRole.OWNER)
    user_a = await make_account(role=UserRole.USER)
    user_b = await make_account(role=UserRole.USER)
    await make_deposit(user_a)
    await make_deposit(user_b)

    response = await client.get("/owner/deposits", headers=_auth_headers(owner))

    assert response.status_code == 200
    assert response.json()["total"] == 2


async def test_owner_gets_deposit_by_id(client, make_account, make_deposit):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    deposit = await make_deposit(user)

    response = await client.get(f"/owner/deposits/{deposit.id}", headers=_auth_headers(owner))

    assert response.status_code == 200
    assert response.json()["id"] == str(deposit.id)


async def test_owner_gets_nonexistent_deposit_returns_404(client, make_account):
    owner = await make_account(role=UserRole.OWNER)

    response = await client.get(f"/owner/deposits/{uuid.uuid4()}", headers=_auth_headers(owner))

    assert response.status_code == 404


async def test_owner_filters_deposits_by_status(client, make_account, make_deposit):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await make_deposit(user, status=DepositStatus.WAITING)
    await make_deposit(user, status=DepositStatus.CREDITED, tx_hash="owner_filter_tx")

    response = await client.get(
        "/owner/deposits", params={"status": "credited"}, headers=_auth_headers(owner)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["status"] == DepositStatus.CREDITED.value


async def test_owner_filters_deposits_by_account_id(client, make_account, make_deposit):
    owner = await make_account(role=UserRole.OWNER)
    user_a = await make_account(role=UserRole.USER)
    user_b = await make_account(role=UserRole.USER)
    await make_deposit(user_a)
    await make_deposit(user_b)

    response = await client.get(
        "/owner/deposits", params={"account_id": str(user_a.id)}, headers=_auth_headers(owner)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["account_id"] == str(user_a.id)


async def test_owner_searches_deposits_by_public_id(client, make_account, make_deposit):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    deposit = await make_deposit(user)
    await make_deposit(user)

    response = await client.get(
        "/owner/deposits", params={"search": deposit.public_id}, headers=_auth_headers(owner)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["public_id"] == deposit.public_id


async def test_owner_filters_deposits_by_tx_hash(client, make_account, make_deposit):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await make_deposit(user, status=DepositStatus.DETECTED, tx_hash="find_me_tx")
    await make_deposit(user)

    response = await client.get(
        "/owner/deposits", params={"tx_hash": "find_me_tx"}, headers=_auth_headers(owner)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["tx_hash"] == "find_me_tx"


async def test_owner_deposits_pagination(client, make_account, make_deposit):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    for _ in range(3):
        await make_deposit(user, expected_amount=Decimal("50"))

    response = await client.get(
        "/owner/deposits", params={"limit": 2, "offset": 0}, headers=_auth_headers(owner)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2


async def test_user_forbidden_from_owner_deposits(client, make_account):
    user = await make_account(role=UserRole.USER)

    response = await client.get("/owner/deposits", headers=_auth_headers(user))

    assert response.status_code == 403


async def test_merchant_forbidden_from_owner_deposits(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.get("/owner/deposits", headers=_auth_headers(merchant))

    assert response.status_code == 403


async def test_owner_deposits_require_authentication(client):
    response = await client.get("/owner/deposits")
    assert response.status_code == 401


async def test_owner_has_no_force_credit_endpoint():
    from app.main import app as fastapi_app

    schema = fastapi_app.openapi()
    allowed_posts = {
        "/owner/deposits/unmatched/{transfer_id}/link",
        "/owner/deposits/unmatched/{transfer_id}/reprocess",
        "/owner/deposits/unmatched/{transfer_id}/ignore",
    }
    for path, methods in schema["paths"].items():
        if path.startswith("/owner/deposits"):
            if "post" in methods:
                assert path in allowed_posts
            assert "patch" not in methods
            assert "put" not in methods
            assert "credit" not in path
