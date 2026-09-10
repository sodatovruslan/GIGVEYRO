import hashlib
import hmac
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.security import create_access_token
from app.enums.account import UserRole
from app.enums.webhook import WebhookDeliveryStatus
from app.models.deposit import Deposit
from app.models.webhook import Webhook, WebhookDelivery
from app.repositories.webhook import WebhookDeliveryRepository, WebhookRepository
from app.services.webhook import WebhookService
from app.workers.jobs.webhook_delivery import _SIGNATURE_HEADER, _deliver_one


def _auth_headers(account) -> dict:
    token = create_access_token(account.id, account.role.value)
    return {"Authorization": f"Bearer {token}"}


class _FakeResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


class _FakeClient:
    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc
        self.calls: list[dict] = []

    async def post(self, url, *, content, headers):
        self.calls.append({"url": url, "content": content, "headers": headers})
        if self._exc is not None:
            raise self._exc
        return self._response


async def _make_webhook_and_delivery(
    db_session, merchant, *, attempts: int = 0, max_attempts: int = 5
):
    webhook_repo = WebhookRepository(db_session)
    delivery_repo = WebhookDeliveryRepository(db_session)
    service = WebhookService(webhook_repo, delivery_repo)
    webhook, raw_secret = await service.create(
        merchant, url="https://example.com/hook", event_types=["invoice.paid"]
    )
    delivery = WebhookDelivery(
        webhook_id=webhook.id,
        event_type="invoice.paid",
        payload={"invoice_id": "abc"},
        status=WebhookDeliveryStatus.PENDING,
        attempts=attempts,
        max_attempts=max_attempts,
    )
    delivery = await delivery_repo.create(delivery)
    return webhook, raw_secret, delivery, webhook_repo, delivery_repo, service


async def test_successful_delivery_is_signed_and_marked_success(db_session, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)
    webhook, raw_secret, delivery, webhook_repo, delivery_repo, service = (
        await _make_webhook_and_delivery(db_session, merchant)
    )
    client = _FakeClient(response=_FakeResponse(200))

    await _deliver_one(client, webhook_repo, service, delivery_repo, delivery)

    assert delivery.status == WebhookDeliveryStatus.SUCCESS
    assert delivery.attempts == 1
    assert delivery.delivered_at is not None
    call = client.calls[0]
    expected_sig = hmac.new(
        raw_secret.encode("utf-8"), call["content"], hashlib.sha256
    ).hexdigest()
    assert call["headers"][_SIGNATURE_HEADER] == f"sha256={expected_sig}"


async def test_failed_status_schedules_retry(db_session, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)
    webhook, _raw, delivery, webhook_repo, delivery_repo, service = (
        await _make_webhook_and_delivery(db_session, merchant, attempts=0, max_attempts=5)
    )
    client = _FakeClient(response=_FakeResponse(500, "server error"))

    await _deliver_one(client, webhook_repo, service, delivery_repo, delivery)

    assert delivery.status == WebhookDeliveryStatus.PENDING
    assert delivery.attempts == 1
    assert delivery.next_attempt_at is not None
    assert delivery.next_attempt_at > datetime.now(UTC)


async def test_marked_failed_after_max_attempts(db_session, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)
    webhook, _raw, delivery, webhook_repo, delivery_repo, service = (
        await _make_webhook_and_delivery(db_session, merchant, attempts=4, max_attempts=5)
    )
    client = _FakeClient(response=_FakeResponse(500))

    await _deliver_one(client, webhook_repo, service, delivery_repo, delivery)

    assert delivery.attempts == 5
    assert delivery.status == WebhookDeliveryStatus.FAILED


async def test_network_error_schedules_retry(db_session, make_account):
    import httpx

    merchant = await make_account(role=UserRole.MERCHANT)
    webhook, _raw, delivery, webhook_repo, delivery_repo, service = (
        await _make_webhook_and_delivery(db_session, merchant)
    )
    client = _FakeClient(exc=httpx.ConnectError("boom"))

    await _deliver_one(client, webhook_repo, service, delivery_repo, delivery)

    assert delivery.status == WebhookDeliveryStatus.PENDING
    assert delivery.attempts == 1
    assert "boom" in delivery.last_error


async def test_invoice_paid_enqueues_webhook_delivery(
    client, make_account, make_merchant_wallet, db_session
):
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant)
    await client.post(
        "/merchant/webhooks",
        json={"url": "https://example.com/hook", "event_types": ["invoice.paid"]},
        headers=_auth_headers(merchant),
    )
    owner = await make_account(role=UserRole.OWNER)

    create = await client.post(
        "/merchant/invoices", json={"amount": "8"}, headers=_auth_headers(merchant)
    )
    invoice_id = create.json()["id"]
    result = await db_session.execute(select(Deposit).where(Deposit.invoice_id == invoice_id))
    deposit = result.scalar_one()

    simulate = await client.post(
        f"/owner/dev/deposits/{deposit.id}/simulate",
        json={
            "tx_hash": "0xwebhooktest",
            "amount": "8",
            "confirmations": 20,
            "network": "TRC20",
            "asset": "USDT",
            "destination_address": deposit.deposit_address,
        },
        headers=_auth_headers(owner),
    )
    assert simulate.status_code == 200

    webhook_result = await db_session.execute(
        select(Webhook).where(Webhook.merchant_id == merchant.id)
    )
    webhook = webhook_result.scalar_one()
    delivery_result = await db_session.execute(
        select(WebhookDelivery).where(WebhookDelivery.webhook_id == webhook.id)
    )
    delivery = delivery_result.scalar_one()
    assert delivery.event_type == "invoice.paid"
    assert delivery.payload["invoice_id"] == invoice_id
    assert delivery.status == WebhookDeliveryStatus.PENDING
