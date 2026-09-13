import uuid
from decimal import Decimal

from sqlalchemy import select

from app.core.config import settings as app_settings
from app.core.security import create_access_token
from app.enums.account import UserRole
from app.enums.webhook import WebhookDeliveryStatus
from app.models.deposit import Deposit
from app.models.webhook import WebhookDelivery


def _auth_headers(account) -> dict:
    token = create_access_token(account.id, account.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _create_invoice(client, merchant, amount="25.00000000") -> dict:
    response = await client.post(
        "/merchant/invoices", json={"amount": amount}, headers=_auth_headers(merchant)
    )
    assert response.status_code == 201
    return response.json()


async def _linked_deposit(db_session, invoice_id) -> Deposit:
    result = await db_session.execute(select(Deposit).where(Deposit.invoice_id == invoice_id))
    deposit = result.scalar_one_or_none()
    assert deposit is not None
    return deposit


async def _simulate(client, owner, deposit_id, *, tx_hash: str, amount, confirmations: int = 20):
    return await client.post(
        f"/owner/dev/deposits/{deposit_id}/simulate",
        json={
            "tx_hash": tx_hash,
            "amount": str(amount),
            "confirmations": confirmations,
            "network": "TRC20",
            "asset": "USDT",
            "destination_address": app_settings.USDT_TRC20_DEPOSIT_ADDRESS,
        },
        headers=_auth_headers(owner),
    )


async def _timeline(client, merchant, invoice_id):
    return await client.get(
        f"/merchant/invoices/{invoice_id}/timeline", headers=_auth_headers(merchant)
    )


def _event_types(body: dict) -> list[str]:
    return [event["type"] for event in body["events"]]


# ---- 1. ACCESS / TENANCY -------------------------------------------------


async def test_owner_of_invoice_can_view_timeline(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)
    invoice = await _create_invoice(client, merchant)

    response = await _timeline(client, merchant, invoice["id"])

    assert response.status_code == 200
    body = response.json()
    assert body["invoice"]["id"] == invoice["id"]


async def test_unknown_invoice_returns_404(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await _timeline(client, merchant, str(uuid.uuid4()))

    assert response.status_code == 404


async def test_cross_merchant_access_is_denied_with_404(client, make_account):
    merchant_a = await make_account(role=UserRole.MERCHANT)
    merchant_b = await make_account(role=UserRole.MERCHANT)
    invoice = await _create_invoice(client, merchant_a)

    response = await _timeline(client, merchant_b, invoice["id"])

    assert response.status_code == 404


async def test_user_role_is_blocked(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)
    user = await make_account(role=UserRole.USER)
    invoice = await _create_invoice(client, merchant)

    response = await _timeline(client, user, invoice["id"])

    assert response.status_code == 403


async def test_owner_cannot_use_merchant_only_route(client, make_account):
    """Same RBAC as the existing GET /merchant/invoices/{id} - OWNER has its
    own oversight surfaces (deposits, treasury) rather than this merchant
    route, so this is parity, not a new restriction."""
    merchant = await make_account(role=UserRole.MERCHANT)
    owner = await make_account(role=UserRole.OWNER)
    invoice = await _create_invoice(client, merchant)

    response = await _timeline(client, owner, invoice["id"])

    assert response.status_code == 403


async def test_owner_deposit_oversight_still_works_after_change(
    client, make_account, make_merchant_wallet, db_session
):
    """Non-regression: owner's existing dev-simulate/oversight path used to
    seed this feature's own tests must remain functional."""
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant, available=Decimal("0"))
    owner = await make_account(role=UserRole.OWNER)
    invoice = await _create_invoice(client, merchant)
    deposit = await _linked_deposit(db_session, invoice["id"])

    response = await _simulate(
        client, owner, deposit.id, tx_hash="0xownercheck", amount=Decimal("25.00000000")
    )

    assert response.status_code == 200


# ---- 2. EVENT DERIVATION --------------------------------------------------


async def test_fresh_invoice_has_only_created_event(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)
    invoice = await _create_invoice(client, merchant)

    response = await _timeline(client, merchant, invoice["id"])

    body = response.json()
    assert _event_types(body) == ["invoice.created"]
    assert body["deposit"]["status"] == "waiting"
    assert body["ledger_entry"] is None
    assert body["webhook_deliveries"] == []


async def test_deposit_and_credit_events_appear_after_payment(
    client, make_account, make_merchant_wallet, db_session
):
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant, available=Decimal("0"))
    owner = await make_account(role=UserRole.OWNER)
    invoice = await _create_invoice(client, merchant, amount="25.00000000")
    deposit = await _linked_deposit(db_session, invoice["id"])

    simulate = await _simulate(
        client, owner, deposit.id, tx_hash="0xtimeline1", amount=Decimal("25.00000000")
    )
    assert simulate.status_code == 200

    response = await _timeline(client, merchant, invoice["id"])
    body = response.json()

    types = _event_types(body)
    for expected in ["invoice.created", "deposit.detected", "deposit.confirmed", "deposit.credited", "invoice.balance_credited", "invoice.paid"]:
        assert expected in types, f"missing {expected} in {types}"

    assert body["deposit"]["status"] == "credited"
    assert body["deposit"]["tx_hash"] == "0xtimeline1"
    assert body["invoice"]["status"] == "paid"
    assert body["invoice"]["paid_at"] is not None


async def test_ledger_entry_reflects_credited_amount_only(
    client, make_account, make_merchant_wallet, db_session
):
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant, available=Decimal("0"))
    owner = await make_account(role=UserRole.OWNER)
    invoice = await _create_invoice(client, merchant, amount="12.50000000")
    deposit = await _linked_deposit(db_session, invoice["id"])
    await _simulate(client, owner, deposit.id, tx_hash="0xtimeline2", amount=Decimal("12.50000000"))

    response = await _timeline(client, merchant, invoice["id"])
    body = response.json()

    assert body["ledger_entry"]["amount"] == "12.50000000"
    assert body["ledger_entry"]["type"] == "deposit_credit"
    # No raw before/after balance snapshot is ever exposed.
    assert "available_before" not in body["ledger_entry"]
    assert "available_after" not in body["ledger_entry"]


async def test_invoice_paid_timestamp_matches_invoice_record(
    client, make_account, make_merchant_wallet, db_session
):
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant, available=Decimal("0"))
    owner = await make_account(role=UserRole.OWNER)
    invoice = await _create_invoice(client, merchant, amount="5")
    deposit = await _linked_deposit(db_session, invoice["id"])
    await _simulate(client, owner, deposit.id, tx_hash="0xtimeline3", amount=Decimal("5"))

    response = await _timeline(client, merchant, invoice["id"])
    body = response.json()

    paid_event = next(e for e in body["events"] if e["type"] == "invoice.paid")
    assert paid_event["at"] == body["invoice"]["paid_at"]


# ---- 3. WEBHOOKS ------------------------------------------------------


async def test_webhook_delivery_appears_after_invoice_paid(
    client, make_account, make_merchant_wallet, db_session
):
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant, available=Decimal("0"))
    owner = await make_account(role=UserRole.OWNER)
    await client.post(
        "/merchant/webhooks",
        json={"url": "https://example.com/hook", "event_types": ["invoice.paid"]},
        headers=_auth_headers(merchant),
    )
    invoice = await _create_invoice(client, merchant, amount="7")
    deposit = await _linked_deposit(db_session, invoice["id"])
    await _simulate(client, owner, deposit.id, tx_hash="0xtimeline4", amount=Decimal("7"))

    response = await _timeline(client, merchant, invoice["id"])
    body = response.json()

    assert len(body["webhook_deliveries"]) == 1
    delivery = body["webhook_deliveries"][0]
    assert delivery["event_type"] == "invoice.paid"
    assert delivery["status"] == "pending"
    assert any(e["type"] == "webhook.pending" for e in body["events"])


async def test_multiple_webhooks_each_produce_their_own_delivery(
    client, make_account, make_merchant_wallet, db_session
):
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant, available=Decimal("0"))
    owner = await make_account(role=UserRole.OWNER)
    for url in ["https://example.com/hook-a", "https://example.com/hook-b"]:
        await client.post(
            "/merchant/webhooks",
            json={"url": url, "event_types": ["invoice.paid"]},
            headers=_auth_headers(merchant),
        )
    invoice = await _create_invoice(client, merchant, amount="9")
    deposit = await _linked_deposit(db_session, invoice["id"])
    await _simulate(client, owner, deposit.id, tx_hash="0xtimeline5", amount=Decimal("9"))

    response = await _timeline(client, merchant, invoice["id"])
    body = response.json()

    assert len(body["webhook_deliveries"]) == 2
    webhook_ids = {d["webhook_id"] for d in body["webhook_deliveries"]}
    assert len(webhook_ids) == 2


async def test_failed_webhook_delivery_is_represented_without_fake_timestamp(
    client, make_account, db_session
):
    merchant = await make_account(role=UserRole.MERCHANT)
    create = await client.post(
        "/merchant/webhooks",
        json={"url": "https://example.com/hook", "event_types": ["invoice.paid"]},
        headers=_auth_headers(merchant),
    )
    webhook_id = create.json()["id"]
    invoice = await _create_invoice(client, merchant, amount="3")

    # Simulate an exhausted-retries delivery directly (the delivery engine
    # itself is out of scope for this feature and isn't exercised here).
    delivery = WebhookDelivery(
        webhook_id=uuid.UUID(webhook_id),
        event_type="invoice.paid",
        payload={"invoice_id": invoice["id"]},
        status=WebhookDeliveryStatus.FAILED,
        attempts=5,
        max_attempts=5,
        last_response_status=500,
        last_error="connection timed out",
    )
    db_session.add(delivery)
    await db_session.commit()

    response = await _timeline(client, merchant, invoice["id"])
    body = response.json()

    assert len(body["webhook_deliveries"]) == 1
    failed = body["webhook_deliveries"][0]
    assert failed["status"] == "failed"
    assert failed["attempts"] == 5
    assert failed["last_error"] == "connection timed out"
    assert failed["delivered_at"] is None
    failed_event = next(e for e in body["events"] if e["type"] == "webhook.failed")
    # Anchored on created_at - there is no dedicated "failed_at" column, so
    # no timestamp is invented for the exact moment retries were exhausted.
    assert failed_event["at"] == failed["created_at"]


async def test_webhook_deliveries_are_tenant_scoped(client, make_account, db_session):
    merchant_a = await make_account(role=UserRole.MERCHANT)
    merchant_b = await make_account(role=UserRole.MERCHANT)
    create = await client.post(
        "/merchant/webhooks",
        json={"url": "https://example.com/hook", "event_types": ["invoice.paid"]},
        headers=_auth_headers(merchant_b),
    )
    other_webhook_id = create.json()["id"]
    invoice = await _create_invoice(client, merchant_a, amount="4")

    # Merchant B's webhook happens to carry the same invoice_id in its
    # payload (spoofed/coincidental) - it must never leak into A's timeline.
    delivery = WebhookDelivery(
        webhook_id=uuid.UUID(other_webhook_id),
        event_type="invoice.paid",
        payload={"invoice_id": invoice["id"]},
        status=WebhookDeliveryStatus.PENDING,
    )
    db_session.add(delivery)
    await db_session.commit()

    response = await _timeline(client, merchant_a, invoice["id"])
    body = response.json()

    assert body["webhook_deliveries"] == []


# ---- 4. ROBUSTNESS / MISSING DATA -----------------------------------------


async def test_missing_deposit_does_not_crash(client, make_account, db_session):
    merchant = await make_account(role=UserRole.MERCHANT)
    invoice = await _create_invoice(client, merchant, amount="1")
    deposit = await _linked_deposit(db_session, invoice["id"])
    await db_session.delete(deposit)
    await db_session.commit()

    response = await _timeline(client, merchant, invoice["id"])

    assert response.status_code == 200
    body = response.json()
    assert body["deposit"] is None
    assert body["ledger_entry"] is None
    assert _event_types(body) == ["invoice.created"]


async def test_no_webhooks_configured_gives_empty_list_not_crash(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)
    invoice = await _create_invoice(client, merchant, amount="1")

    response = await _timeline(client, merchant, invoice["id"])

    assert response.status_code == 200
    assert response.json()["webhook_deliveries"] == []


async def test_missing_optional_timestamps_do_not_crash(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)
    invoice = await _create_invoice(client, merchant, amount="1")

    response = await _timeline(client, merchant, invoice["id"])

    assert response.status_code == 200
    body = response.json()
    assert body["deposit"]["detected_at"] is None
    assert body["deposit"]["confirmed_at"] is None
    assert body["deposit"]["credited_at"] is None
    assert body["deposit"]["failed_at"] is None


# ---- 5. SERIALIZATION / ORDERING / SECURITY -------------------------------


async def test_amounts_are_decimal_safe_strings(
    client, make_account, make_merchant_wallet, db_session
):
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant, available=Decimal("0"))
    owner = await make_account(role=UserRole.OWNER)
    invoice = await _create_invoice(client, merchant, amount="0.10000001")
    deposit = await _linked_deposit(db_session, invoice["id"])
    await _simulate(client, owner, deposit.id, tx_hash="0xtimeline6", amount=Decimal("0.10000001"))

    response = await _timeline(client, merchant, invoice["id"])
    body = response.json()

    assert body["invoice"]["amount"] == "0.10000001"
    assert body["deposit"]["received_amount"] == "0.10000001"
    assert body["ledger_entry"]["amount"] == "0.10000001"
    for field in (body["invoice"]["amount"], body["deposit"]["received_amount"]):
        assert "e" not in field.lower()


async def test_events_are_sorted_and_deterministic_across_calls(
    client, make_account, make_merchant_wallet, db_session
):
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant, available=Decimal("0"))
    owner = await make_account(role=UserRole.OWNER)
    invoice = await _create_invoice(client, merchant, amount="6")
    deposit = await _linked_deposit(db_session, invoice["id"])
    await _simulate(client, owner, deposit.id, tx_hash="0xtimeline7", amount=Decimal("6"))

    first = (await _timeline(client, merchant, invoice["id"])).json()
    second = (await _timeline(client, merchant, invoice["id"])).json()

    timestamps = [event["at"] for event in first["events"]]
    assert timestamps == sorted(timestamps)
    assert _event_types(first) == _event_types(second)


async def test_no_secret_or_internal_field_leakage(
    client, make_account, make_merchant_wallet, db_session
):
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant, available=Decimal("0"))
    owner = await make_account(role=UserRole.OWNER)
    await client.post(
        "/merchant/webhooks",
        json={"url": "https://example.com/hook", "event_types": ["invoice.paid"]},
        headers=_auth_headers(merchant),
    )
    invoice = await _create_invoice(client, merchant, amount="8")
    deposit = await _linked_deposit(db_session, invoice["id"])
    await _simulate(client, owner, deposit.id, tx_hash="0xtimeline8", amount=Decimal("8"))

    raw = (await _timeline(client, merchant, invoice["id"])).text

    for forbidden in [
        "encrypted_secret",
        "available_before",
        "available_after",
        "insurance_before",
        "insurance_after",
        "frozen_before",
        "frozen_after",
        "held_before",
        "held_after",
        "idempotency_key",
        "provider_event_id",
        "key_hash",
    ]:
        assert forbidden not in raw
