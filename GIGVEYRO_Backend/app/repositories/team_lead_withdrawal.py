import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums.withdrawal import WithdrawalStatus
from app.models.team_lead_withdrawal import TeamLeadWithdrawal


class TeamLeadWithdrawalRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_id(self, withdrawal_id: uuid.UUID) -> TeamLeadWithdrawal | None:
        return await self._session.get(TeamLeadWithdrawal, withdrawal_id)

    async def get_by_id_for_update(self, withdrawal_id: uuid.UUID) -> TeamLeadWithdrawal | None:
        result = await self._session.execute(
            select(TeamLeadWithdrawal).where(TeamLeadWithdrawal.id == withdrawal_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def create(self, withdrawal: TeamLeadWithdrawal) -> TeamLeadWithdrawal:
        self._session.add(withdrawal)
        await self._session.flush()
        await self._session.refresh(withdrawal)
        return withdrawal

    async def save(self, withdrawal: TeamLeadWithdrawal) -> TeamLeadWithdrawal:
        await self._session.flush()
        await self._session.refresh(withdrawal)
        return withdrawal

    async def list_for_team_lead(
        self, team_lead_id: uuid.UUID, *, status: WithdrawalStatus | None, limit: int, offset: int
    ) -> list[TeamLeadWithdrawal]:
        query = select(TeamLeadWithdrawal).where(TeamLeadWithdrawal.team_lead_id == team_lead_id)
        if status is not None:
            query = query.where(TeamLeadWithdrawal.status == status)
        query = query.order_by(TeamLeadWithdrawal.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def count_for_team_lead(
        self, team_lead_id: uuid.UUID, *, status: WithdrawalStatus | None
    ) -> int:
        query = (
            select(func.count())
            .select_from(TeamLeadWithdrawal)
            .where(TeamLeadWithdrawal.team_lead_id == team_lead_id)
        )
        if status is not None:
            query = query.where(TeamLeadWithdrawal.status == status)
        result = await self._session.execute(query)
        return result.scalar_one()

    async def sum_pending_for_team_lead(self, team_lead_id: uuid.UUID) -> Decimal:
        result = await self._session.execute(
            select(func.coalesce(func.sum(TeamLeadWithdrawal.amount), 0)).where(
                TeamLeadWithdrawal.team_lead_id == team_lead_id,
                TeamLeadWithdrawal.status.in_(
                    [WithdrawalStatus.PENDING, WithdrawalStatus.APPROVED]
                ),
            )
        )
        return Decimal(result.scalar_one())

    async def list_all(
        self,
        *,
        status: WithdrawalStatus | None,
        team_lead_id: uuid.UUID | None,
        search: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
        limit: int,
        offset: int,
    ) -> list[TeamLeadWithdrawal]:
        query = self._filtered(
            select(TeamLeadWithdrawal),
            status=status,
            team_lead_id=team_lead_id,
            search=search,
            date_from=date_from,
            date_to=date_to,
        )
        query = query.order_by(TeamLeadWithdrawal.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def count_all(
        self,
        *,
        status: WithdrawalStatus | None,
        team_lead_id: uuid.UUID | None,
        search: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> int:
        query = self._filtered(
            select(func.count()).select_from(TeamLeadWithdrawal),
            status=status,
            team_lead_id=team_lead_id,
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
        team_lead_id: uuid.UUID | None,
        search: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> Select:
        if status is not None:
            query = query.where(TeamLeadWithdrawal.status == status)
        if team_lead_id is not None:
            query = query.where(TeamLeadWithdrawal.team_lead_id == team_lead_id)
        if search:
            query = query.where(TeamLeadWithdrawal.public_id.ilike(f"%{search}%"))
        if date_from is not None:
            query = query.where(TeamLeadWithdrawal.created_at >= date_from)
        if date_to is not None:
            query = query.where(TeamLeadWithdrawal.created_at <= date_to)
        return query
