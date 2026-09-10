import uuid
from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums.withdrawal import WithdrawalStatus
from app.models.user_withdrawal import UserWithdrawal


class UserWithdrawalRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_id(self, withdrawal_id: uuid.UUID) -> UserWithdrawal | None:
        return await self._session.get(UserWithdrawal, withdrawal_id)

    async def get_by_id_for_update(self, withdrawal_id: uuid.UUID) -> UserWithdrawal | None:
        result = await self._session.execute(
            select(UserWithdrawal).where(UserWithdrawal.id == withdrawal_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def create(self, withdrawal: UserWithdrawal) -> UserWithdrawal:
        self._session.add(withdrawal)
        await self._session.flush()
        await self._session.refresh(withdrawal)
        return withdrawal

    async def save(self, withdrawal: UserWithdrawal) -> UserWithdrawal:
        await self._session.flush()
        await self._session.refresh(withdrawal)
        return withdrawal

    async def list_for_user(
        self, user_id: uuid.UUID, *, status: WithdrawalStatus | None, limit: int, offset: int
    ) -> list[UserWithdrawal]:
        query = select(UserWithdrawal).where(UserWithdrawal.user_id == user_id)
        if status is not None:
            query = query.where(UserWithdrawal.status == status)
        query = query.order_by(UserWithdrawal.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def count_for_user(self, user_id: uuid.UUID, *, status: WithdrawalStatus | None) -> int:
        query = (
            select(func.count())
            .select_from(UserWithdrawal)
            .where(UserWithdrawal.user_id == user_id)
        )
        if status is not None:
            query = query.where(UserWithdrawal.status == status)
        result = await self._session.execute(query)
        return result.scalar_one()

    async def list_all(
        self,
        *,
        status: WithdrawalStatus | None,
        user_id: uuid.UUID | None,
        search: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
        limit: int,
        offset: int,
    ) -> list[UserWithdrawal]:
        query = self._filtered(
            select(UserWithdrawal),
            status=status,
            user_id=user_id,
            search=search,
            date_from=date_from,
            date_to=date_to,
        )
        query = query.order_by(UserWithdrawal.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def count_all(
        self,
        *,
        status: WithdrawalStatus | None,
        user_id: uuid.UUID | None,
        search: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> int:
        query = self._filtered(
            select(func.count()).select_from(UserWithdrawal),
            status=status,
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
        status: WithdrawalStatus | None,
        user_id: uuid.UUID | None,
        search: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> Select:
        if status is not None:
            query = query.where(UserWithdrawal.status == status)
        if user_id is not None:
            query = query.where(UserWithdrawal.user_id == user_id)
        if search:
            query = query.where(UserWithdrawal.public_id.ilike(f"%{search}%"))
        if date_from is not None:
            query = query.where(UserWithdrawal.created_at >= date_from)
        if date_to is not None:
            query = query.where(UserWithdrawal.created_at <= date_to)
        return query
