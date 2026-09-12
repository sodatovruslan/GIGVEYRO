import secrets
import uuid
from typing import Any

from app.core.totp_crypto import decrypt_totp_secret, encrypt_totp_secret
from app.core.url_safety import resolve_public_address
from app.enums.webhook import WebhookDeliveryStatus, WebhookStatus
from app.models.account import Account
from app.models.webhook import Webhook, WebhookDelivery
from app.repositories.webhook import WebhookDeliveryRepository, WebhookRepository


class WebhookNotFoundError(Exception):
    """Covers a missing webhook and one that exists but isn't visible to the caller."""


def generate_webhook_secret() -> str:
    return secrets.token_urlsafe(32)


class WebhookService:
    def __init__(
        self, repository: WebhookRepository, delivery_repository: WebhookDeliveryRepository
    ):
        self._webhooks = repository
        self._deliveries = delivery_repository

    async def create(
        self, merchant: Account, *, url: str, event_types: list[str]
    ) -> tuple[Webhook, str]:
        # Raises UnsafeWebhookURLError (a ValueError subclass) if the host
        # resolves to a private/loopback/link-local/etc address - the
        # route maps that to a 422 for the merchant.
        await resolve_public_address(url)
        raw_secret = generate_webhook_secret()
        webhook = Webhook(
            merchant_id=merchant.id,
            url=url,
            encrypted_secret=encrypt_totp_secret(raw_secret),
            event_types=event_types,
            status=WebhookStatus.ACTIVE,
        )
        webhook = await self._webhooks.create(webhook)
        return webhook, raw_secret

    async def get_for_merchant(self, merchant_id: uuid.UUID, webhook_id: uuid.UUID) -> Webhook:
        webhook = await self._get_or_raise(webhook_id)
        if webhook.merchant_id != merchant_id:
            raise WebhookNotFoundError()
        return webhook

    async def list_for_merchant(
        self, merchant_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[list[Webhook], int]:
        items = await self._webhooks.list_for_merchant(merchant_id, limit=limit, offset=offset)
        total = await self._webhooks.count_for_merchant(merchant_id)
        return items, total

    async def update(
        self,
        merchant_id: uuid.UUID,
        webhook_id: uuid.UUID,
        *,
        url: str | None,
        status: WebhookStatus | None,
        event_types: list[str] | None,
    ) -> Webhook:
        webhook = await self._webhooks.get_by_id_for_update(webhook_id)
        if webhook is None or webhook.merchant_id != merchant_id:
            raise WebhookNotFoundError()
        if url is not None:
            await resolve_public_address(url)
            webhook.url = url
        if status is not None:
            webhook.status = status
        if event_types is not None:
            webhook.event_types = event_types
        return await self._webhooks.save(webhook)

    async def list_deliveries_for_merchant(
        self, merchant_id: uuid.UUID, webhook_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[list[WebhookDelivery], int]:
        await self.get_for_merchant(merchant_id, webhook_id)  # ownership check
        items = await self._deliveries.list_for_webhook(webhook_id, limit=limit, offset=offset)
        total = await self._deliveries.count_for_webhook(webhook_id)
        return items, total

    async def enqueue_delivery(
        self, merchant_id: uuid.UUID, event_type: str, payload: dict[str, Any]
    ) -> list[WebhookDelivery]:
        """Creates one pending WebhookDelivery per ACTIVE merchant webhook
        subscribed to event_type. Call from within the same transaction as
        the event that triggers it (mirrors the realtime outbox pattern) -
        an ARQ cron job (webhook_delivery.py) polls and sends these."""
        webhooks = await self._webhooks.list_active_for_merchant_event(merchant_id, event_type)
        deliveries = []
        for webhook in webhooks:
            delivery = WebhookDelivery(
                webhook_id=webhook.id,
                event_type=event_type,
                payload=payload,
                status=WebhookDeliveryStatus.PENDING,
            )
            deliveries.append(await self._deliveries.create(delivery))
        return deliveries

    def decrypt_secret(self, webhook: Webhook) -> str:
        return decrypt_totp_secret(webhook.encrypted_secret)

    async def _get_or_raise(self, webhook_id: uuid.UUID) -> Webhook:
        webhook = await self._webhooks.get_by_id(webhook_id)
        if webhook is None:
            raise WebhookNotFoundError()
        return webhook
