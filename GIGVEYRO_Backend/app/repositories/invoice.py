import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums.invoice import InvoiceStatus
from app.models.invoice import Invoice


class InvoiceRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_id(self, invoice_id: uuid.UUID) -> Invoice | None:
        return await self._session.get(Invoice, invoice_id)

    async def get_by_id_for_update(self, invoice_id: uuid.UUID) -> Invoice | None:
        result = await self._session.execute(
            select(Invoice).where(Invoice.id == invoice_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_by_public_id(self, public_id: str) -> Invoice | None:
        result = await self._session.execute(
            select(Invoice).where(Invoice.public_id == public_id)
        )
        return result.scalar_one_or_none()

    async def create(self, invoice: Invoice) -> Invoice:
        self._session.add(invoice)
        await self._session.flush()
        await self._session.refresh(invoice)
        return invoice

    async def save(self, invoice: Invoice) -> Invoice:
        await self._session.flush()
        await self._session.refresh(invoice)
        return invoice

    async def list_for_merchant(
        self, merchant_id: uuid.UUID, *, status: InvoiceStatus | None, limit: int, offset: int
    ) -> list[Invoice]:
        query = select(Invoice).where(Invoice.merchant_id == merchant_id)
        if status is not None:
            query = query.where(Invoice.status == status)
        query = query.order_by(Invoice.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def count_for_merchant(
        self, merchant_id: uuid.UUID, *, status: InvoiceStatus | None
    ) -> int:
        query = select(func.count()).select_from(Invoice).where(Invoice.merchant_id == merchant_id)
        if status is not None:
            query = query.where(Invoice.status == status)
        result = await self._session.execute(query)
        return result.scalar_one()

    async def expire_stale_pending(self) -> None:
        await self._session.execute(
            update(Invoice)
            .where(
                Invoice.status == InvoiceStatus.PENDING_PAYMENT,
                Invoice.expires_at <= func.now(),
            )
            .values(status=InvoiceStatus.EXPIRED)
        )
