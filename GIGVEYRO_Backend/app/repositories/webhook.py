import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums.webhook import WebhookDeliveryStatus, WebhookStatus
from app.models.webhook import Webhook, WebhookDelivery


class WebhookRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_id(self, webhook_id: uuid.UUID) -> Webhook | None:
        return await self._session.get(Webhook, webhook_id)

    async def get_by_id_for_update(self, webhook_id: uuid.UUID) -> Webhook | None:
        result = await self._session.execute(
            select(Webhook).where(Webhook.id == webhook_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def create(self, webhook: Webhook) -> Webhook:
        self._session.add(webhook)
        await self._session.flush()
        await self._session.refresh(webhook)
        return webhook

    async def save(self, webhook: Webhook) -> Webhook:
        await self._session.flush()
        await self._session.refresh(webhook)
        return webhook

    async def list_for_merchant(
        self, merchant_id: uuid.UUID, *, limit: int, offset: int
    ) -> list[Webhook]:
        query = (
            select(Webhook)
            .where(Webhook.merchant_id == merchant_id)
            .order_by(Webhook.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def count_for_merchant(self, merchant_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(Webhook).where(Webhook.merchant_id == merchant_id)
        )
        return result.scalar_one()

    async def list_active_for_merchant_event(
        self, merchant_id: uuid.UUID, event_type: str
    ) -> list[Webhook]:
        query = select(Webhook).where(
            Webhook.merchant_id == merchant_id,
            Webhook.status == WebhookStatus.ACTIVE,
            Webhook.event_types.contains([event_type]),
        )
        result = await self._session.execute(query)
        return list(result.scalars().all())


class WebhookDeliveryRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, delivery: WebhookDelivery) -> WebhookDelivery:
        self._session.add(delivery)
        await self._session.flush()
        await self._session.refresh(delivery)
        return delivery

    async def save(self, delivery: WebhookDelivery) -> WebhookDelivery:
        await self._session.flush()
        await self._session.refresh(delivery)
        return delivery

    async def pending(self, limit: int = 50) -> Sequence[WebhookDelivery]:
        now = datetime.now(UTC)
        result = await self._session.execute(
            select(WebhookDelivery)
            .where(
                WebhookDelivery.status == WebhookDeliveryStatus.PENDING,
                WebhookDelivery.attempts < WebhookDelivery.max_attempts,
                or_(
                    WebhookDelivery.next_attempt_at.is_(None),
                    WebhookDelivery.next_attempt_at <= now,
                ),
            )
            .order_by(WebhookDelivery.created_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return result.scalars().all()

    async def list_for_webhook(
        self, webhook_id: uuid.UUID, *, limit: int, offset: int
    ) -> list[WebhookDelivery]:
        query = (
            select(WebhookDelivery)
            .where(WebhookDelivery.webhook_id == webhook_id)
            .order_by(WebhookDelivery.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def count_for_webhook(self, webhook_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(WebhookDelivery)
            .where(WebhookDelivery.webhook_id == webhook_id)
        )
        return result.scalar_one()

    async def list_for_invoice(
        self, merchant_id: uuid.UUID, invoice_id: uuid.UUID
    ) -> list[WebhookDelivery]:
        """Deliveries carry no invoice_id column - the only linkage is the
        JSONB payload set at enqueue time (see deposit.py::_credit). Scoping
        the join by Webhook.merchant_id (not just filtering the invoice_id)
        is what keeps this tenant-safe: a delivery can only be returned if
        it belongs to a webhook owned by the requesting merchant."""
        query = (
            select(WebhookDelivery)
            .join(Webhook, WebhookDelivery.webhook_id == Webhook.id)
            .where(
                Webhook.merchant_id == merchant_id,
                WebhookDelivery.payload["invoice_id"].astext == str(invoice_id),
            )
            .order_by(WebhookDelivery.created_at.asc())
        )
        result = await self._session.execute(query)
        return list(result.scalars().all())
