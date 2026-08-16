import uuid
from decimal import Decimal

from app.core.config import settings as app_settings
from app.core.security import create_access_token
from app.enums.account import UserRole
from app.enums.deposit import DepositStatus
from app.enums.wallet import BalanceBucket, LedgerEntryType
from app.schemas.deposit import DepositRead


def _auth_headers(account) -> dict:
    token = create_access_token(account.id, account.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _simulate(
    client,
    owner,
    deposit_id,
    *,
    tx_hash: str,
    amount,
    confirmations: int,
    network: str = "TRC20",
    asset: str = "USDT",
    destination_address: str | None = None,
):
    if destination_address is None:
        destination_address = app_settings.USDT_TRC20_DEPOSIT_ADDRESS
    return await client.post(
        f"/owner/dev/deposits/{deposit_id}/simulate",
        json={
            "tx_hash": tx_hash,
            "amount": str(amount),
            "confirmations": confirmations,
            "network": network,
            "asset": asset,
            "destination_address": destination_address,
        },
        headers=_auth_headers(owner),
    )


# ---- SCHEMA SANITY --------------------------------------------------------


def test_deposit_read_schema_has_no_secret_fields():
    field_names = set(DepositRead.model_fields.keys())
    forbidden = {"private_key", "seed", "mnemonic", "api_secret", "password"}
    assert not (field_names & forbidden)


# ---- CREATE ---------------------------------------------------------------


async def test_user_creates_deposit(client, make_account):
    user = await make_account(role=UserRole.USER)

    response = await client.post(
        "/deposits", json={"amount": "100.00000000"}, headers=_auth_headers(user)
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == DepositStatus.WAITING.value
    assert body["expected_amount"] == "100.00000000"
    assert body["deposit_address"] == app_settings.USDT_TRC20_DEPOSIT_ADDRESS
    assert body["network"] == "TRC20"
    assert body["asset"] == "USDT"
    assert body["public_id"].startswith("DEP-")
    assert body["tx_hash"] is None


async def test_create_deposit_rejects_zero_amount(client, make_account):
    user = await make_account(role=UserRole.USER)

    response = await client.post(
        "/deposits", json={"amount": "0"}, headers=_auth_headers(user)
    )

    assert response.status_code == 422


async def test_create_deposit_rejects_negative_amount(client, make_account):
    user = await make_account(role=UserRole.USER)

    response = await client.post(
        "/deposits", json={"amount": "-10"}, headers=_auth_headers(user)
    )

    assert response.status_code == 422


async def test_merchant_cannot_create_deposit(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.post(
        "/deposits", json={"amount": "100"}, headers=_auth_headers(merchant)
    )

    assert response.status_code == 403


async def test_owner_cannot_create_deposit(client, make_account):
    owner = await make_account(role=UserRole.OWNER)

    response = await client.post(
        "/deposits", json={"amount": "100"}, headers=_auth_headers(owner)
    )

    assert response.status_code == 403


# ---- READ -------------------------------------------------------------


async def test_user_lists_own_deposits(client, make_account, make_deposit):
    user = await make_account(role=UserRole.USER)
    await make_deposit(user)
    await make_deposit(user)

    response = await client.get("/deposits", headers=_auth_headers(user))

    assert response.status_code == 200
    assert response.json()["total"] == 2


async def test_user_gets_own_deposit_detail(client, make_account, make_deposit):
    user = await make_account(role=UserRole.USER)
    deposit = await make_deposit(user)

    response = await client.get(f"/deposits/{deposit.id}", headers=_auth_headers(user))

    assert response.status_code == 200
    assert response.json()["id"] == str(deposit.id)


async def test_user_cannot_see_another_users_deposit(client, make_account, make_deposit):
    user_a = await make_account(role=UserRole.USER)
    user_b = await make_account(role=UserRole.USER)
    deposit = await make_deposit(user_a)

    response = await client.get(f"/deposits/{deposit.id}", headers=_auth_headers(user_b))

    assert response.status_code == 404


async def test_get_nonexistent_deposit_returns_404(client, make_account):
    user = await make_account(role=UserRole.USER)

    response = await client.get(f"/deposits/{uuid.uuid4()}", headers=_auth_headers(user))

    assert response.status_code == 404


async def test_deposits_require_authentication(client):
    response = await client.get("/deposits")
    assert response.status_code == 401


# ---- EXPIRATION -----------------------------------------------------------


async def test_waiting_deposit_expires(client, make_account, make_deposit):
    user = await make_account(role=UserRole.USER)
    deposit = await make_deposit(user, expires_in_minutes=-1)

    response = await client.get(f"/deposits/{deposit.id}", headers=_auth_headers(user))

    assert response.status_code == 200
    assert response.json()["status"] == DepositStatus.EXPIRED.value


async def test_detected_deposit_does_not_expire_from_intent_ttl(
    client, make_account, make_deposit
):
    user = await make_account(role=UserRole.USER)
    deposit = await make_deposit(
        user,
        status=DepositStatus.DETECTED,
        tx_hash="already_detected_tx",
        received_amount=Decimal("100"),
        expires_in_minutes=-1,
    )

    response = await client.get(f"/deposits/{deposit.id}", headers=_auth_headers(user))

    assert response.status_code == 200
    assert response.json()["status"] == DepositStatus.DETECTED.value


# ---- DETECTION --------------------------------------------------------


async def test_valid_mock_transaction_is_detected(client, make_account, make_deposit):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    deposit = await make_deposit(user)

    response = await _simulate(
        client, owner, deposit.id, tx_hash="tx_detect_001", amount=Decimal("100"), confirmations=0
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == DepositStatus.DETECTED.value
    assert body["tx_hash"] == "tx_detect_001"
    assert body["received_amount"] == "100.00000000"


async def test_wrong_network_rejected(client, make_account, make_deposit):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    deposit = await make_deposit(user)

    response = await _simulate(
        client,
        owner,
        deposit.id,
        tx_hash="tx_wrong_net",
        amount=Decimal("100"),
        confirmations=0,
        network="ERC20",
    )

    assert response.status_code == 422

    check = await client.get(f"/deposits/{deposit.id}", headers=_auth_headers(user))
    assert check.json()["status"] == DepositStatus.WAITING.value


async def test_wrong_asset_rejected(client, make_account, make_deposit):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    deposit = await make_deposit(user)

    response = await client.post(
        f"/owner/dev/deposits/{deposit.id}/simulate",
        json={
            "tx_hash": "tx_wrong_asset",
            "amount": "100",
            "confirmations": 0,
            "network": "TRC20",
            "asset": "BTC",
            "destination_address": app_settings.USDT_TRC20_DEPOSIT_ADDRESS,
        },
        headers=_auth_headers(owner),
    )

    assert response.status_code == 422


async def test_wrong_destination_rejected(client, make_account, make_deposit):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    deposit = await make_deposit(user)

    response = await _simulate(
        client,
        owner,
        deposit.id,
        tx_hash="tx_wrong_dest",
        amount=Decimal("100"),
        confirmations=0,
        destination_address="SOME_OTHER_ADDRESS",
    )

    assert response.status_code == 422

    check = await client.get(f"/deposits/{deposit.id}", headers=_auth_headers(user))
    assert check.json()["status"] == DepositStatus.WAITING.value


async def test_duplicate_tx_hash_rejected(client, make_account, make_deposit):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    deposit_a = await make_deposit(user)
    deposit_b = await make_deposit(user)

    first = await _simulate(
        client, owner, deposit_a.id, tx_hash="tx_dup_001", amount=Decimal("100"), confirmations=0
    )
    assert first.status_code == 200

    second = await _simulate(
        client, owner, deposit_b.id, tx_hash="tx_dup_001", amount=Decimal("100"), confirmations=0
    )
    assert second.status_code == 409


async def test_merchant_cannot_use_dev_simulate_endpoint(client, make_account, make_deposit):
    merchant = await make_account(role=UserRole.MERCHANT)
    user = await make_account(role=UserRole.USER)
    deposit = await make_deposit(user)

    response = await _simulate(
        client, merchant, deposit.id, tx_hash="tx_forbidden", amount=Decimal("100"), confirmations=0
    )

    assert response.status_code == 403


# ---- CONFIRMATIONS ------------------------------------------------------


async def test_zero_confirmations_stays_detected(client, make_account, make_deposit):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    deposit = await make_deposit(user)

    response = await _simulate(
        client, owner, deposit.id, tx_hash="tx_conf_0", amount=Decimal("100"), confirmations=0
    )

    assert response.json()["status"] == DepositStatus.DETECTED.value


async def test_below_required_confirmations_stays_confirming(client, make_account, make_deposit):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    deposit = await make_deposit(user, required_confirmations=20)

    response = await _simulate(
        client, owner, deposit.id, tx_hash="tx_conf_5", amount=Decimal("100"), confirmations=5
    )

    body = response.json()
    assert body["status"] == DepositStatus.CONFIRMING.value
    assert body["confirmations"] == 5


async def test_exactly_required_confirmations_credits(
    client, make_account, make_wallet, make_deposit
):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await make_wallet(user)
    deposit = await make_deposit(user, required_confirmations=20)

    response = await _simulate(
        client, owner, deposit.id, tx_hash="tx_conf_20", amount=Decimal("100"), confirmations=20
    )

    assert response.json()["status"] == DepositStatus.CREDITED.value


async def test_above_required_confirmations_credits(
    client, make_account, make_wallet, make_deposit
):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await make_wallet(user)
    deposit = await make_deposit(user, required_confirmations=20)

    response = await _simulate(
        client, owner, deposit.id, tx_hash="tx_conf_30", amount=Decimal("100"), confirmations=30
    )

    assert response.json()["status"] == DepositStatus.CREDITED.value


async def test_replaying_lower_confirmations_does_not_reduce_count(
    client, make_account, make_deposit
):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    deposit = await make_deposit(user, required_confirmations=20)

    first = await _simulate(
        client, owner, deposit.id, tx_hash="tx_replay", amount=Decimal("100"), confirmations=15
    )
    assert first.json()["confirmations"] == 15
    assert first.json()["status"] == DepositStatus.CONFIRMING.value

    second = await _simulate(
        client, owner, deposit.id, tx_hash="tx_replay", amount=Decimal("100"), confirmations=5
    )
    assert second.json()["confirmations"] == 15
    assert second.json()["status"] == DepositStatus.CONFIRMING.value


# ---- AMOUNT POLICY ------------------------------------------------------


async def test_exact_amount_match_credits(client, make_account, make_wallet, make_deposit):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await make_wallet(user)
    deposit = await make_deposit(user, expected_amount=Decimal("100"), required_confirmations=1)

    response = await _simulate(
        client, owner, deposit.id, tx_hash="tx_exact", amount=Decimal("100"), confirmations=1
    )

    assert response.json()["status"] == DepositStatus.CREDITED.value


async def test_underpayment_causes_amount_mismatch(client, make_account, make_deposit):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    deposit = await make_deposit(user, expected_amount=Decimal("100"))

    response = await _simulate(
        client, owner, deposit.id, tx_hash="tx_under", amount=Decimal("99"), confirmations=0
    )

    assert response.json()["status"] == DepositStatus.AMOUNT_MISMATCH.value

    wallet_resp = await client.get("/wallet", headers=_auth_headers(user))
    # no wallet exists yet for a bare make_account() USER - the important
    # assertion is that this deposit was never credited, checked via ledger
    ledger_resp = await client.get("/deposits", headers=_auth_headers(user))
    assert ledger_resp.json()["items"][0]["credited_amount"] is None
    assert wallet_resp.status_code in (404, 200)


async def test_overpayment_causes_amount_mismatch(client, make_account, make_deposit):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    deposit = await make_deposit(user, expected_amount=Decimal("100"))

    response = await _simulate(
        client, owner, deposit.id, tx_hash="tx_over", amount=Decimal("101"), confirmations=0
    )

    assert response.json()["status"] == DepositStatus.AMOUNT_MISMATCH.value


# ---- CREDIT -------------------------------------------------------------


async def test_credit_increases_available_leaves_insurance_and_frozen_unchanged(
    client, make_account, make_wallet, make_deposit
):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("50"), insurance=Decimal("10"), frozen=Decimal("5"))
    deposit = await make_deposit(user, expected_amount=Decimal("100"), required_confirmations=1)

    await _simulate(
        client, owner, deposit.id, tx_hash="tx_credit", amount=Decimal("100"), confirmations=1
    )

    wallet_resp = await client.get("/wallet", headers=_auth_headers(user))
    body = wallet_resp.json()
    assert body["available_balance"] == "150.00000000"
    assert body["insurance_balance"] == "10.00000000"
    assert body["frozen_balance"] == "5.00000000"


async def test_credit_creates_deposit_credit_ledger_entry(
    client, make_account, make_wallet, make_deposit
):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("50"))
    deposit = await make_deposit(user, expected_amount=Decimal("100"), required_confirmations=1)

    await _simulate(
        client, owner, deposit.id, tx_hash="tx_ledger", amount=Decimal("100"), confirmations=1
    )

    ledger_resp = await client.get("/wallet/ledger", headers=_auth_headers(user))
    items = ledger_resp.json()["items"]
    assert len(items) == 1
    entry = items[0]
    assert entry["type"] == LedgerEntryType.DEPOSIT_CREDIT.value
    assert entry["balance_bucket"] == BalanceBucket.AVAILABLE.value
    assert entry["amount"] == "100.00000000"
    assert entry["available_before"] == "50.00000000"
    assert entry["available_after"] == "150.00000000"


async def test_credited_deposit_has_credited_amount_and_timestamp(
    client, make_account, make_wallet, make_deposit
):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await make_wallet(user)
    deposit = await make_deposit(user, expected_amount=Decimal("100"), required_confirmations=1)

    response = await _simulate(
        client, owner, deposit.id, tx_hash="tx_final", amount=Decimal("100"), confirmations=1
    )

    body = response.json()
    assert body["status"] == DepositStatus.CREDITED.value
    assert body["credited_amount"] == "100.00000000"
    assert body["credited_at"] is not None


# ---- IDEMPOTENCY --------------------------------------------------------


async def test_same_confirmed_event_sent_twice_does_not_double_credit(
    client, make_account, make_wallet, make_deposit
):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await make_wallet(user)
    deposit = await make_deposit(user, expected_amount=Decimal("100"), required_confirmations=1)

    await _simulate(
        client, owner, deposit.id, tx_hash="tx_twice", amount=Decimal("100"), confirmations=1
    )
    await _simulate(
        client, owner, deposit.id, tx_hash="tx_twice", amount=Decimal("100"), confirmations=1
    )

    wallet_resp = await client.get("/wallet", headers=_auth_headers(user))
    assert wallet_resp.json()["available_balance"] == "100.00000000"

    ledger_resp = await client.get("/wallet/ledger", headers=_auth_headers(user))
    assert ledger_resp.json()["total"] == 1


async def test_confirmed_event_replayed_many_times_does_not_double_credit(
    client, make_account, make_wallet, make_deposit
):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await make_wallet(user)
    deposit = await make_deposit(user, expected_amount=Decimal("100"), required_confirmations=1)

    for _ in range(5):
        await _simulate(
            client, owner, deposit.id,
            tx_hash="tx_replay_many", amount=Decimal("100"), confirmations=1,
        )

    wallet_resp = await client.get("/wallet", headers=_auth_headers(user))
    assert wallet_resp.json()["available_balance"] == "100.00000000"
