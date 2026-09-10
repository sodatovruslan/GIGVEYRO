from decimal import Decimal

from sqlalchemy import select

from app.core.config import settings as app_settings
from app.core.security import create_access_token
from app.enums.account import UserRole
from app.enums.deposit import DepositStatus
from app.models.deposit import Deposit


def _auth_headers(account) -> dict:
    token = create_access_token(account.id, account.role.value)
    return {"Authorization": f"Bearer {token}"}


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


# ---- CREATE -----------------------------------------------------------


async def test_merchant_creates_invoice(client, make_account, db_session):
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.post(
        "/merchant/invoices",
        json={"amount": "50.00000000", "description": "Order #1"},
        headers=_auth_headers(merchant),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending_payment"
    assert body["amount"] == "50.00000000"
    assert body["public_id"].startswith("INV-")
    assert body["deposit_address"] == app_settings.USDT_TRC20_DEPOSIT_ADDRESS

    deposit = await _linked_deposit(db_session, body["id"])
    assert deposit.account_id == merchant.id
    assert deposit.expected_amount == Decimal("50.00000000")
    assert deposit.status == DepositStatus.WAITING


async def test_user_cannot_create_invoice(client, make_account):
    user = await make_account(role=UserRole.USER)

    response = await client.post(
        "/merchant/invoices", json={"amount": "10"}, headers=_auth_headers(user)
    )

    assert response.status_code == 403


async def test_create_invoice_rejects_zero_amount(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.post(
        "/merchant/invoices", json={"amount": "0"}, headers=_auth_headers(merchant)
    )

    assert response.status_code == 422


# ---- TENANT ISOLATION ---------------------------------------------------


async def test_merchant_cannot_see_another_merchants_invoice(client, make_account):
    merchant_a = await make_account(role=UserRole.MERCHANT)
    merchant_b = await make_account(role=UserRole.MERCHANT)

    create = await client.post(
        "/merchant/invoices", json={"amount": "20"}, headers=_auth_headers(merchant_a)
    )
    invoice_id = create.json()["id"]

    response = await client.get(
        f"/merchant/invoices/{invoice_id}", headers=_auth_headers(merchant_b)
    )

    assert response.status_code == 404


async def test_merchant_lists_only_own_invoices(client, make_account):
    merchant_a = await make_account(role=UserRole.MERCHANT)
    merchant_b = await make_account(role=UserRole.MERCHANT)

    await client.post(
        "/merchant/invoices", json={"amount": "20"}, headers=_auth_headers(merchant_a)
    )
    await client.post(
        "/merchant/invoices", json={"amount": "30"}, headers=_auth_headers(merchant_b)
    )

    response = await client.get("/merchant/invoices", headers=_auth_headers(merchant_a))

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["merchant_id"] == str(merchant_a.id)


# ---- CANCEL -------------------------------------------------------------


async def test_merchant_cancels_invoice_and_fails_linked_deposit(client, make_account, db_session):
    merchant = await make_account(role=UserRole.MERCHANT)
    create = await client.post(
        "/merchant/invoices", json={"amount": "40"}, headers=_auth_headers(merchant)
    )
    invoice_id = create.json()["id"]

    response = await client.post(
        f"/merchant/invoices/{invoice_id}/cancel", headers=_auth_headers(merchant)
    )

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"

    deposit = await _linked_deposit(db_session, invoice_id)
    assert deposit.status == DepositStatus.FAILED


async def test_cannot_cancel_already_cancelled_invoice(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)
    create = await client.post(
        "/merchant/invoices", json={"amount": "40"}, headers=_auth_headers(merchant)
    )
    invoice_id = create.json()["id"]
    await client.post(f"/merchant/invoices/{invoice_id}/cancel", headers=_auth_headers(merchant))

    response = await client.post(
        f"/merchant/invoices/{invoice_id}/cancel", headers=_auth_headers(merchant)
    )

    assert response.status_code == 409


# ---- PUBLIC PAYMENT PAGE -------------------------------------------------


async def test_public_invoice_read_hides_merchant_identity(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)
    create = await client.post(
        "/merchant/invoices", json={"amount": "15"}, headers=_auth_headers(merchant)
    )
    public_id = create.json()["public_id"]

    response = await client.get(f"/invoices/{public_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["public_id"] == public_id
    assert body["amount"] == "15.00000000"
    assert "merchant_id" not in body
    assert "id" not in body


async def test_public_invoice_not_found(client):
    response = await client.get("/invoices/INV-DOESNOTEXIST")

    assert response.status_code == 404


# ---- CREDIT / PAYMENT FLOW ------------------------------------------------


async def test_invoice_paid_on_matching_deposit_credit(
    client, make_account, make_merchant_wallet, db_session
):
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant, available=Decimal("0"))
    owner = await make_account(role=UserRole.OWNER)

    create = await client.post(
        "/merchant/invoices", json={"amount": "25.00000000"}, headers=_auth_headers(merchant)
    )
    invoice_id = create.json()["id"]
    deposit = await _linked_deposit(db_session, invoice_id)

    simulate = await _simulate(
        client, owner, deposit.id, tx_hash="0xinvoicepaid1", amount=Decimal("25.00000000")
    )
    assert simulate.status_code == 200
    assert simulate.json()["status"] == "credited"

    invoice_response = await client.get(
        f"/merchant/invoices/{invoice_id}", headers=_auth_headers(merchant)
    )
    assert invoice_response.json()["status"] == "paid"
    assert invoice_response.json()["paid_at"] is not None

    wallet_response = await client.get("/merchant/wallet", headers=_auth_headers(merchant))
    assert wallet_response.json()["available_balance"] == "25.00000000"


async def test_invoice_credit_does_not_touch_user_wallet(
    client, make_account, make_merchant_wallet, db_session
):
    """The invoice-linked deposit's account_id is the merchant - crediting it
    must never attempt (or fall back) to credit a UserWallet."""
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant, available=Decimal("0"))
    owner = await make_account(role=UserRole.OWNER)

    create = await client.post(
        "/merchant/invoices", json={"amount": "5"}, headers=_auth_headers(merchant)
    )
    deposit = await _linked_deposit(db_session, create.json()["id"])

    simulate = await _simulate(
        client, owner, deposit.id, tx_hash="0xinvoicepaid2", amount=Decimal("5")
    )

    assert simulate.status_code == 200
    assert simulate.json()["status"] == "credited"
