import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums.withdrawal import WithdrawalStatus
from app.models.withdrawal import MerchantWithdrawal

_MONEY_QUANTUM = Decimal("0.00000001")


class WithdrawalRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_id(self, withdrawal_id: uuid.UUID) -> MerchantWithdrawal | None:
        return await self._session.get(MerchantWithdrawal, withdrawal_id)

    async def get_by_id_for_update(self, withdrawal_id: uuid.UUID) -> MerchantWithdrawal | None:
        result = await self._session.execute(
            select(MerchantWithdrawal)
            .where(MerchantWithdrawal.id == withdrawal_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def create(self, withdrawal: MerchantWithdrawal) -> MerchantWithdrawal:
        self._session.add(withdrawal)
        await self._session.flush()
        await self._session.refresh(withdrawal)
        return withdrawal

    async def save(self, withdrawal: MerchantWithdrawal) -> MerchantWithdrawal:
        await self._session.flush()
        await self._session.refresh(withdrawal)
        return withdrawal

    async def list_for_merchant(
        self, merchant_id: uuid.UUID, *, status: WithdrawalStatus | None, limit: int, offset: int
    ) -> list[MerchantWithdrawal]:
        query = select(MerchantWithdrawal).where(MerchantWithdrawal.merchant_id == merchant_id)
        if status is not None:
            query = query.where(MerchantWithdrawal.status == status)
        query = query.order_by(MerchantWithdrawal.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def count_for_merchant(
        self, merchant_id: uuid.UUID, *, status: WithdrawalStatus | None
    ) -> int:
        query = (
            select(func.count())
            .select_from(MerchantWithdrawal)
            .where(MerchantWithdrawal.merchant_id == merchant_id)
        )
        if status is not None:
            query = query.where(MerchantWithdrawal.status == status)
        result = await self._session.execute(query)
        return result.scalar_one()

    async def list_all(
        self,
        *,
        status: WithdrawalStatus | None,
        merchant_id: uuid.UUID | None,
        search: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
        limit: int,
        offset: int,
    ) -> list[MerchantWithdrawal]:
        query = self._filtered(
            select(MerchantWithdrawal),
            status=status,
            merchant_id=merchant_id,
            search=search,
            date_from=date_from,
            date_to=date_to,
        )
        query = query.order_by(MerchantWithdrawal.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def count_all(
        self,
        *,
        status: WithdrawalStatus | None,
        merchant_id: uuid.UUID | None,
        search: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> int:
        query = self._filtered(
            select(func.count()).select_from(MerchantWithdrawal),
            status=status,
            merchant_id=merchant_id,
            search=search,
            date_from=date_from,
            date_to=date_to,
        )
        result = await self._session.execute(query)
        return result.scalar_one()

    async def stats_for_merchant(self, merchant_id: uuid.UUID) -> dict[str, int | Decimal]:
        counts_query = (
            select(MerchantWithdrawal.status, func.count())
            .where(MerchantWithdrawal.merchant_id == merchant_id)
            .group_by(MerchantWithdrawal.status)
        )
        counts_result = await self._session.execute(counts_query)
        counts = {status.value: count for status, count in counts_result.all()}

        volume_query = select(func.coalesce(func.sum(MerchantWithdrawal.amount), 0)).where(
            MerchantWithdrawal.merchant_id == merchant_id,
            MerchantWithdrawal.status == WithdrawalStatus.PAID,
        )
        volume_result = await self._session.execute(volume_query)
        paid_volume = volume_result.scalar_one()

        return {
            "total": sum(counts.values()),
            "pending": counts.get(WithdrawalStatus.PENDING.value, 0),
            "approved": counts.get(WithdrawalStatus.APPROVED.value, 0),
            "paid": counts.get(WithdrawalStatus.PAID.value, 0),
            "rejected": counts.get(WithdrawalStatus.REJECTED.value, 0),
            "cancelled": counts.get(WithdrawalStatus.CANCELLED.value, 0),
            "paid_volume": Decimal(paid_volume).quantize(_MONEY_QUANTUM),
        }

    @staticmethod
    def _filtered(
        query: Select,
        *,
        status: WithdrawalStatus | None,
        merchant_id: uuid.UUID | None,
        search: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> Select:
        if status is not None:
            query = query.where(MerchantWithdrawal.status == status)
        if merchant_id is not None:
            query = query.where(MerchantWithdrawal.merchant_id == merchant_id)
        if search:
            query = query.where(MerchantWithdrawal.public_id.ilike(f"%{search}%"))
        if date_from is not None:
            query = query.where(MerchantWithdrawal.created_at >= date_from)
        if date_to is not None:
            query = query.where(MerchantWithdrawal.created_at <= date_to)
        return query
