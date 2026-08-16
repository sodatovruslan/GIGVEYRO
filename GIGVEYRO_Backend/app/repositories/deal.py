import uuid
from datetime import datetime

from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums.deal import DealStatus
from app.models.deal import Deal


class DealRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_id(self, deal_id: uuid.UUID) -> Deal | None:
        return await self._session.get(Deal, deal_id)

    async def get_by_id_for_update(self, deal_id: uuid.UUID) -> Deal | None:
        result = await self._session.execute(
            select(Deal).where(Deal.id == deal_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def create(self, deal: Deal) -> Deal:
        self._session.add(deal)
        await self._session.flush()
        await self._session.refresh(deal)
        return deal

    async def save(self, deal: Deal) -> Deal:
        await self._session.flush()
        await self._session.refresh(deal)
        return deal

    async def expire_stale_available(self) -> None:
        """Bulk-flip AVAILABLE deals past their expiry to EXPIRED. Called
        before any listing/read path - there is no background worker in
        Stage 7, expiration is purely lazy."""
        await self._session.execute(
            update(Deal)
            .where(Deal.status == DealStatus.AVAILABLE, Deal.expires_at <= func.now())
            .values(status=DealStatus.EXPIRED)
        )

    async def list_available(self, *, limit: int, offset: int) -> list[Deal]:
        result = await self._session.execute(
            select(Deal)
            .where(Deal.status == DealStatus.AVAILABLE, Deal.expires_at > func.now())
            .order_by(Deal.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def count_available(self) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(Deal)
            .where(Deal.status == DealStatus.AVAILABLE, Deal.expires_at > func.now())
        )
        return result.scalar_one()

    async def list_for_merchant(
        self, merchant_id: uuid.UUID, *, status: DealStatus | None, limit: int, offset: int
    ) -> list[Deal]:
        query = select(Deal).where(Deal.merchant_id == merchant_id)
        if status is not None:
            query = query.where(Deal.status == status)
        query = query.order_by(Deal.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def count_for_merchant(self, merchant_id: uuid.UUID, *, status: DealStatus | None) -> int:
        query = select(func.count()).select_from(Deal).where(Deal.merchant_id == merchant_id)
        if status is not None:
            query = query.where(Deal.status == status)
        result = await self._session.execute(query)
        return result.scalar_one()

    async def list_for_user(
        self, user_id: uuid.UUID, *, status: DealStatus | None, limit: int, offset: int
    ) -> list[Deal]:
        query = select(Deal).where(Deal.user_id == user_id)
        if status is not None:
            query = query.where(Deal.status == status)
        query = query.order_by(Deal.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def count_for_user(self, user_id: uuid.UUID, *, status: DealStatus | None) -> int:
        query = select(func.count()).select_from(Deal).where(Deal.user_id == user_id)
        if status is not None:
            query = query.where(Deal.status == status)
        result = await self._session.execute(query)
        return result.scalar_one()

    async def list_all(
        self,
        *,
        status: DealStatus | None,
        merchant_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        search: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
        limit: int,
        offset: int,
    ) -> list[Deal]:
        query = self._filtered(
            select(Deal),
            status=status,
            merchant_id=merchant_id,
            user_id=user_id,
            search=search,
            date_from=date_from,
            date_to=date_to,
        )
        query = query.order_by(Deal.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def count_all(
        self,
        *,
        status: DealStatus | None,
        merchant_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        search: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> int:
        query = self._filtered(
            select(func.count()).select_from(Deal),
            status=status,
            merchant_id=merchant_id,
            user_id=user_id,
            search=search,
            date_from=date_from,
            date_to=date_to,
        )
        result = await self._session.execute(query)
        return result.scalar_one()

    @staticmethod
    def _filtered(
        query: Select,
        *,
        status: DealStatus | None,
        merchant_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        search: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> Select:
        if status is not None:
            query = query.where(Deal.status == status)
        if merchant_id is not None:
            query = query.where(Deal.merchant_id == merchant_id)
        if user_id is not None:
            query = query.where(Deal.user_id == user_id)
        if search:
            query = query.where(Deal.public_id.ilike(f"%{search}%"))
        if date_from is not None:
            query = query.where(Deal.created_at >= date_from)
        if date_to is not None:
            query = query.where(Deal.created_at <= date_to)
        return query
