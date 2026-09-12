import uuid
from decimal import Decimal

from app.core.security import create_access_token
from app.enums.account import UserRole
from app.enums.wallet import BalanceBucket, LedgerEntryType


def _auth_headers(account) -> dict:
    token = create_access_token(account.id, account.role.value)
    return {"Authorization": f"Bearer {token}"}


# ---- WALLET CREATION (via Stage 4 account creation flow) ------------------


async def test_creating_user_account_creates_zero_balance_wallet(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    username = f"newuser_{uuid.uuid4().hex[:8]}"

    create_resp = await client.post(
        "/owner/accounts",
        json={
            "username": username,
            "password": "NewAccountPass123",
            "role": "user",
            "full_name": "New User",
        },
        headers=_auth_headers(owner),
    )
    account_id = create_resp.json()["id"]

    wallet_resp = await client.get(
        f"/owner/accounts/{account_id}/wallet", headers=_auth_headers(owner)
    )

    assert wallet_resp.status_code == 200
    body = wallet_resp.json()
    assert body["currency"] == "USDT"
    assert body["available_balance"] == "0.00000000"
    assert body["insurance_balance"] == "0.00000000"
    assert body["frozen_balance"] == "0.00000000"


async def test_creating_merchant_account_does_not_create_wallet(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    username = f"newmerchant_{uuid.uuid4().hex[:8]}"

    create_resp = await client.post(
        "/owner/accounts",
        json={
            "username": username,
            "password": "NewAccountPass123",
            "role": "merchant",
            "full_name": "New Merchant",
        },
        headers=_auth_headers(owner),
    )
    account_id = create_resp.json()["id"]

    wallet_resp = await client.get(
        f"/owner/accounts/{account_id}/wallet", headers=_auth_headers(owner)
    )

    assert wallet_resp.status_code == 404


# ---- ALLOCATION -------------------------------------------------------


async def test_owner_allocates_to_user(client, make_account, make_wallet, db_session):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await make_wallet(user)

    response = await client.post(
        f"/owner/accounts/{user.id}/wallet/allocate",
        json={
            "amount": "500.00",
            "description": "initial funding",
            "idempotency_key": "alloc-1",
        },
        headers=_auth_headers(owner),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["available_balance"] == "500.00000000"
    assert body["insurance_balance"] == "0.00000000"
    assert body["frozen_balance"] == "0.00000000"

    ledger_resp = await client.get(
        f"/owner/accounts/{user.id}/wallet/ledger", headers=_auth_headers(owner)
    )
    ledger_body = ledger_resp.json()
    assert ledger_body["total"] == 1
    entry = ledger_body["items"][0]
    assert entry["type"] == LedgerEntryType.OWNER_ALLOCATION.value
    assert entry["balance_bucket"] == BalanceBucket.AVAILABLE.value
    assert entry["amount"] == "500.00000000"
    assert entry["available_before"] == "0.00000000"
    assert entry["available_after"] == "500.00000000"
    assert entry["created_by_account_id"] == str(owner.id)


async def test_allocate_rejects_zero_amount(client, make_account, make_wallet):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await make_wallet(user)

    response = await client.post(
        f"/owner/accounts/{user.id}/wallet/allocate",
        json={"amount": "0", "idempotency_key": "alloc-zero"},
        headers=_auth_headers(owner),
    )

    assert response.status_code == 422


async def test_allocate_rejects_negative_amount(client, make_account, make_wallet):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await make_wallet(user)

    response = await client.post(
        f"/owner/accounts/{user.id}/wallet/allocate",
        json={"amount": "-10", "idempotency_key": "alloc-neg"},
        headers=_auth_headers(owner),
    )

    assert response.status_code == 422


async def test_allocate_requires_idempotency_key(client, make_account, make_wallet):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await make_wallet(user)

    response = await client.post(
        f"/owner/accounts/{user.id}/wallet/allocate",
        json={"amount": "100"},
        headers=_auth_headers(owner),
    )

    assert response.status_code == 422

    ledger_resp = await client.get(
        f"/owner/accounts/{user.id}/wallet/ledger", headers=_auth_headers(owner)
    )
    assert ledger_resp.json()["total"] == 0


async def test_allocate_rejects_merchant_target(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.post(
        f"/owner/accounts/{merchant.id}/wallet/allocate",
        json={"amount": "100", "idempotency_key": "alloc-merchant"},
        headers=_auth_headers(owner),
    )

    assert response.status_code == 404


async def test_allocate_rejects_owner_target(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    other_owner = await make_account(role=UserRole.OWNER)

    response = await client.post(
        f"/owner/accounts/{other_owner.id}/wallet/allocate",
        json={"amount": "100", "idempotency_key": "alloc-owner"},
        headers=_auth_headers(owner),
    )

    assert response.status_code == 404


async def test_allocate_rejects_inactive_user(client, make_account, make_wallet):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER, is_active=False)
    await make_wallet(user)

    response = await client.post(
        f"/owner/accounts/{user.id}/wallet/allocate",
        json={"amount": "100", "idempotency_key": "alloc-inactive"},
        headers=_auth_headers(owner),
    )

    assert response.status_code == 409


async def test_allocate_nonexistent_account_returns_404(client, make_account):
    owner = await make_account(role=UserRole.OWNER)

    response = await client.post(
        f"/owner/accounts/{uuid.uuid4()}/wallet/allocate",
        json={"amount": "100", "idempotency_key": "alloc-missing"},
        headers=_auth_headers(owner),
    )

    assert response.status_code == 404


async def test_allocate_rejected_for_non_owner(client, make_account, make_wallet):
    user_actor = await make_account(role=UserRole.USER)
    target = await make_account(role=UserRole.USER)
    await make_wallet(target)

    response = await client.post(
        f"/owner/accounts/{target.id}/wallet/allocate",
        json={"amount": "100", "idempotency_key": "alloc-forbidden"},
        headers=_auth_headers(user_actor),
    )

    assert response.status_code == 403


# ---- IDEMPOTENCY (H3 security fix) ---------------------------------------


async def test_allocate_same_idempotency_key_does_not_double_apply(
    client, make_account, make_wallet
):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await make_wallet(user)

    payload = {"amount": "100.00", "idempotency_key": "retry-key-1"}

    first = await client.post(
        f"/owner/accounts/{user.id}/wallet/allocate", json=payload, headers=_auth_headers(owner)
    )
    second = await client.post(
        f"/owner/accounts/{user.id}/wallet/allocate", json=payload, headers=_auth_headers(owner)
    )

    assert first.status_code == 200
    assert second.status_code == 200
    # Retrying the exact same logical operation returns the same ledger entry.
    assert first.json() == second.json()

    ledger_resp = await client.get(
        f"/owner/accounts/{user.id}/wallet/ledger", headers=_auth_headers(owner)
    )
    ledger_body = ledger_resp.json()
    assert ledger_body["total"] == 1

    wallet_resp = await client.get(
        f"/owner/accounts/{user.id}/wallet", headers=_auth_headers(owner)
    )
    assert wallet_resp.json()["available_balance"] == "100.00000000"


async def test_allocate_different_idempotency_keys_are_independent(
    client, make_account, make_wallet
):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await make_wallet(user)

    for key in ("key-a", "key-b"):
        response = await client.post(
            f"/owner/accounts/{user.id}/wallet/allocate",
            json={"amount": "50.00", "idempotency_key": key},
            headers=_auth_headers(owner),
        )
        assert response.status_code == 200

    ledger_resp = await client.get(
        f"/owner/accounts/{user.id}/wallet/ledger", headers=_auth_headers(owner)
    )
    assert ledger_resp.json()["total"] == 2

    wallet_resp = await client.get(
        f"/owner/accounts/{user.id}/wallet", headers=_auth_headers(owner)
    )
    assert wallet_resp.json()["available_balance"] == "100.00000000"


# ---- INSURANCE ----------------------------------------------------------


async def test_insurance_increase(client, make_account, make_wallet):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await make_wallet(user)

    response = await client.post(
        f"/owner/accounts/{user.id}/wallet/insurance",
        json={
            "amount": "100.00",
            "description": "insurance deposit",
            "idempotency_key": "ins-inc-1",
        },
        headers=_auth_headers(owner),
    )

    assert response.status_code == 200
    assert response.json()["insurance_balance"] == "100.00000000"


async def test_insurance_decrease(client, make_account, make_wallet):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, insurance=Decimal("100"))

    response = await client.post(
        f"/owner/accounts/{user.id}/wallet/insurance",
        json={"amount": "-40.00", "idempotency_key": "ins-dec-1"},
        headers=_auth_headers(owner),
    )

    assert response.status_code == 200
    assert response.json()["insurance_balance"] == "60.00000000"


async def test_insurance_decrease_below_zero_rejected(client, make_account, make_wallet):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, insurance=Decimal("60"))

    response = await client.post(
        f"/owner/accounts/{user.id}/wallet/insurance",
        json={"amount": "-100.00", "idempotency_key": "ins-dec-neg"},
        headers=_auth_headers(owner),
    )

    assert response.status_code == 409


async def test_insurance_requires_idempotency_key(client, make_account, make_wallet):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await make_wallet(user)

    response = await client.post(
        f"/owner/accounts/{user.id}/wallet/insurance",
        json={"amount": "100.00"},
        headers=_auth_headers(owner),
    )

    assert response.status_code == 422


async def test_insurance_ledger_entries_have_correct_snapshots(client, make_account, make_wallet):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await make_wallet(user)

    await client.post(
        f"/owner/accounts/{user.id}/wallet/insurance",
        json={"amount": "100.00", "idempotency_key": "ins-snap-1"},
        headers=_auth_headers(owner),
    )
    await client.post(
        f"/owner/accounts/{user.id}/wallet/insurance",
        json={"amount": "-40.00", "idempotency_key": "ins-snap-2"},
        headers=_auth_headers(owner),
    )

    ledger_resp = await client.get(
        f"/owner/accounts/{user.id}/wallet/ledger", headers=_auth_headers(owner)
    )
    items = ledger_resp.json()["items"]
    assert len(items) == 2
    # most recent first
    assert items[0]["insurance_before"] == "100.00000000"
    assert items[0]["insurance_after"] == "60.00000000"
    assert items[1]["insurance_before"] == "0.00000000"
    assert items[1]["insurance_after"] == "100.00000000"
    assert all(item["type"] == LedgerEntryType.INSURANCE_ADJUSTMENT.value for item in items)


# ---- MANUAL ADJUSTMENT ---------------------------------------------------


async def test_manual_adjust_increase(client, make_account, make_wallet):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("100"))

    response = await client.post(
        f"/owner/accounts/{user.id}/wallet/adjust",
        json={"amount": "50.00", "reason": "bonus", "idempotency_key": "adj-inc-1"},
        headers=_auth_headers(owner),
    )

    assert response.status_code == 200
    assert response.json()["available_balance"] == "150.00000000"


async def test_manual_adjust_decrease(client, make_account, make_wallet):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("100"))

    response = await client.post(
        f"/owner/accounts/{user.id}/wallet/adjust",
        json={"amount": "-20.00", "reason": "correction", "idempotency_key": "adj-dec-1"},
        headers=_auth_headers(owner),
    )

    assert response.status_code == 200
    assert response.json()["available_balance"] == "80.00000000"


async def test_manual_adjust_below_zero_rejected(client, make_account, make_wallet):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("10"))

    response = await client.post(
        f"/owner/accounts/{user.id}/wallet/adjust",
        json={"amount": "-20.00", "reason": "correction", "idempotency_key": "adj-dec-neg"},
        headers=_auth_headers(owner),
    )

    assert response.status_code == 409


async def test_manual_adjust_requires_reason(client, make_account, make_wallet):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("100"))

    response = await client.post(
        f"/owner/accounts/{user.id}/wallet/adjust",
        json={"amount": "10.00", "reason": "", "idempotency_key": "adj-no-reason"},
        headers=_auth_headers(owner),
    )

    assert response.status_code == 422


async def test_manual_adjust_requires_idempotency_key(client, make_account, make_wallet):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("100"))

    response = await client.post(
        f"/owner/accounts/{user.id}/wallet/adjust",
        json={"amount": "10.00", "reason": "bonus"},
        headers=_auth_headers(owner),
    )

    assert response.status_code == 422


# ---- USER ACCESS --------------------------------------------------------


async def test_user_gets_own_wallet(client, make_account, make_wallet):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("250"))

    response = await client.get("/wallet", headers=_auth_headers(user))

    assert response.status_code == 200
    assert response.json()["available_balance"] == "250.00000000"


async def test_user_gets_own_ledger(client, make_account, make_wallet, db_session):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await make_wallet(user)

    await client.post(
        f"/owner/accounts/{user.id}/wallet/allocate",
        json={"amount": "77.00", "idempotency_key": "own-ledger-1"},
        headers=_auth_headers(owner),
    )

    response = await client.get("/wallet/ledger", headers=_auth_headers(user))

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["amount"] == "77.00000000"


async def test_merchant_cannot_access_wallet(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.get("/wallet", headers=_auth_headers(merchant))

    assert response.status_code == 403


async def test_owner_cannot_use_user_wallet_endpoint(client, make_account):
    owner = await make_account(role=UserRole.OWNER)

    response = await client.get("/wallet", headers=_auth_headers(owner))

    assert response.status_code == 403


async def test_wallet_requires_authentication(client):
    response = await client.get("/wallet")
    assert response.status_code == 401


async def test_user_cannot_see_another_users_wallet(client, make_account, make_wallet):
    user_a = await make_account(role=UserRole.USER)
    user_b = await make_account(role=UserRole.USER)
    await make_wallet(user_a, available=Decimal("999"))
    await make_wallet(user_b, available=Decimal("1"))

    response = await client.get("/wallet", headers=_auth_headers(user_b))

    assert response.status_code == 200
    assert response.json()["available_balance"] == "1.00000000"


# ---- OWNER ACCESS ---------------------------------------------------------


async def test_owner_gets_user_wallet(client, make_account, make_wallet):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("42"))

    response = await client.get(f"/owner/accounts/{user.id}/wallet", headers=_auth_headers(owner))

    assert response.status_code == 200
    assert response.json()["available_balance"] == "42.00000000"


async def test_owner_gets_user_ledger(client, make_account, make_wallet):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await make_wallet(user)

    response = await client.get(
        f"/owner/accounts/{user.id}/wallet/ledger", headers=_auth_headers(owner)
    )

    assert response.status_code == 200
    assert response.json()["total"] == 0


async def test_user_forbidden_from_owner_wallet_endpoints(client, make_account, make_wallet):
    user_actor = await make_account(role=UserRole.USER)
    target = await make_account(role=UserRole.USER)
    await make_wallet(target)

    response = await client.get(
        f"/owner/accounts/{target.id}/wallet", headers=_auth_headers(user_actor)
    )

    assert response.status_code == 403


async def test_merchant_forbidden_from_owner_wallet_endpoints(client, make_account, make_wallet):
    merchant_actor = await make_account(role=UserRole.MERCHANT)
    target = await make_account(role=UserRole.USER)
    await make_wallet(target)

    response = await client.get(
        f"/owner/accounts/{target.id}/wallet", headers=_auth_headers(merchant_actor)
    )

    assert response.status_code == 403


# ---- LEDGER IMMUTABILITY --------------------------------------------------


def test_no_mutating_ledger_routes_exist():
    from app.main import app as fastapi_app

    schema = fastapi_app.openapi()
    for path, methods in schema["paths"].items():
        if "ledger" in path:
            assert "patch" not in methods
            assert "delete" not in methods
            assert "put" not in methods
