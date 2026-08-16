import uuid
from datetime import datetime

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums.appeal import AppealReason, AppealStatus
from app.models.appeal import DealAppeal


class AppealRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_id(self, appeal_id: uuid.UUID) -> DealAppeal | None:
        return await self._session.get(DealAppeal, appeal_id)

    async def get_by_id_for_update(self, appeal_id: uuid.UUID) -> DealAppeal | None:
        result = await self._session.execute(
            select(DealAppeal).where(DealAppeal.id == appeal_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_active_by_deal_id(self, deal_id: uuid.UUID) -> DealAppeal | None:
        result = await self._session.execute(
            select(DealAppeal).where(
                DealAppeal.deal_id == deal_id,
                DealAppeal.status.in_([AppealStatus.OPEN, AppealStatus.UNDER_REVIEW]),
            )
        )
        return result.scalar_one_or_none()

    async def create(self, appeal: DealAppeal) -> DealAppeal:
        self._session.add(appeal)
        await self._session.flush()
        await self._session.refresh(appeal)
        return appeal

    async def save(self, appeal: DealAppeal) -> DealAppeal:
        await self._session.flush()
        await self._session.refresh(appeal)
        return appeal

    async def list_for_account(
        self,
        account_id: uuid.UUID,
        *,
        status: AppealStatus | None,
        limit: int,
        offset: int,
    ) -> list[DealAppeal]:
        query = select(DealAppeal).where(DealAppeal.opened_by_account_id == account_id)
        if status is not None:
            query = query.where(DealAppeal.status == status)
        query = query.order_by(DealAppeal.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def count_for_account(
        self, account_id: uuid.UUID, *, status: AppealStatus | None
    ) -> int:
        query = (
            select(func.count())
            .select_from(DealAppeal)
            .where(DealAppeal.opened_by_account_id == account_id)
        )
        if status is not None:
            query = query.where(DealAppeal.status == status)
        result = await self._session.execute(query)
        return result.scalar_one()

    async def list_all(
        self,
        *,
        status: AppealStatus | None,
        reason_code: AppealReason | None,
        merchant_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        search: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
        limit: int,
        offset: int,
    ) -> list[DealAppeal]:
        query = self._filtered(
            select(DealAppeal),
            status=status,
            reason_code=reason_code,
            merchant_id=merchant_id,
            user_id=user_id,
            search=search,
            date_from=date_from,
            date_to=date_to,
        )
        query = query.order_by(DealAppeal.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def count_all(
        self,
        *,
        status: AppealStatus | None,
        reason_code: AppealReason | None,
        merchant_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        search: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> int:
        query = self._filtered(
            select(func.count()).select_from(DealAppeal),
            status=status,
            reason_code=reason_code,
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
        status: AppealStatus | None,
        reason_code: AppealReason | None,
        merchant_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        search: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> Select:
        if status is not None:
            query = query.where(DealAppeal.status == status)
        if reason_code is not None:
            query = query.where(DealAppeal.reason_code == reason_code)
        if search:
            query = query.where(DealAppeal.public_id.ilike(f"%{search}%"))
        if date_from is not None:
            query = query.where(DealAppeal.created_at >= date_from)
        if date_to is not None:
            query = query.where(DealAppeal.created_at <= date_to)
        return query
