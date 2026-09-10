import csv
import io

from app.core.security import create_access_token
from app.enums.account import UserRole


def _auth_headers(account) -> dict:
    token = create_access_token(account.id, account.role.value)
    return {"Authorization": f"Bearer {token}"}


async def test_merchant_statistics_counts_invoices(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)
    await client.post("/merchant/invoices", json={"amount": "10"}, headers=_auth_headers(merchant))
    invoice_two = await client.post(
        "/merchant/invoices", json={"amount": "20"}, headers=_auth_headers(merchant)
    )
    await client.post(
        f"/merchant/invoices/{invoice_two.json()['id']}/cancel", headers=_auth_headers(merchant)
    )

    response = await client.get("/merchant/statistics", headers=_auth_headers(merchant))

    assert response.status_code == 200
    body = response.json()
    assert body["invoices"]["total"] == 2
    assert body["invoices"]["pending_payment"] == 1
    assert body["invoices"]["cancelled"] == 1
    assert body["invoices"]["paid_volume"] == "0.00000000"


async def test_merchant_statistics_isolated_per_merchant(client, make_account):
    merchant_a = await make_account(role=UserRole.MERCHANT)
    merchant_b = await make_account(role=UserRole.MERCHANT)
    await client.post(
        "/merchant/invoices", json={"amount": "10"}, headers=_auth_headers(merchant_a)
    )

    response = await client.get("/merchant/statistics", headers=_auth_headers(merchant_b))

    assert response.status_code == 200
    assert response.json()["invoices"]["total"] == 0


async def test_user_cannot_read_merchant_statistics(client, make_account):
    user = await make_account(role=UserRole.USER)

    response = await client.get("/merchant/statistics", headers=_auth_headers(user))

    assert response.status_code == 403


async def test_merchant_exports_invoices_csv(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)
    await client.post(
        "/merchant/invoices",
        json={"amount": "10", "description": "Order A"},
        headers=_auth_headers(merchant),
    )

    response = await client.get("/merchant/reports/invoices", headers=_auth_headers(merchant))

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(response.text)))
    assert rows[0] == [
        "public_id",
        "amount",
        "status",
        "description",
        "external_reference",
        "created_at",
        "paid_at",
    ]
    assert len(rows) == 2
    assert rows[1][1] == "10.00000000"
    assert rows[1][3] == "Order A"


async def test_csv_export_only_includes_own_invoices(client, make_account):
    merchant_a = await make_account(role=UserRole.MERCHANT)
    merchant_b = await make_account(role=UserRole.MERCHANT)
    await client.post(
        "/merchant/invoices", json={"amount": "10"}, headers=_auth_headers(merchant_a)
    )

    response = await client.get("/merchant/reports/invoices", headers=_auth_headers(merchant_b))

    rows = list(csv.reader(io.StringIO(response.text)))
    assert len(rows) == 1
