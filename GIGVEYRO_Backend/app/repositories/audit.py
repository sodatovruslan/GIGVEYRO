import uuid
from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog


class AuditRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, log_entry: AuditLog) -> AuditLog:
        self._session.add(log_entry)
        await self._session.flush()
        await self._session.refresh(log_entry)
        return log_entry

    async def list_logs(
        self,
        *,
        actor_account_id: uuid.UUID | None = None,
        action: str | None = None,
        entity_type: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AuditLog]:
        query = self._filtered(
            select(AuditLog),
            actor_account_id=actor_account_id,
            action=action,
            entity_type=entity_type,
            date_from=date_from,
            date_to=date_to,
        )
        query = query.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def count_logs(
        self,
        *,
        actor_account_id: uuid.UUID | None = None,
        action: str | None = None,
        entity_type: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> int:
        query = self._filtered(
            select(func.count()).select_from(AuditLog),
            actor_account_id=actor_account_id,
            action=action,
            entity_type=entity_type,
            date_from=date_from,
            date_to=date_to,
        )
        result = await self._session.execute(query)
        return result.scalar_one()

    @staticmethod
    def _filtered(
        query: Select,
        *,
        actor_account_id: uuid.UUID | None,
        action: str | None,
        entity_type: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> Select:
        if actor_account_id is not None:
            query = query.where(AuditLog.actor_account_id == actor_account_id)
        if action:
            query = query.where(AuditLog.action == action)
        if entity_type:
            query = query.where(AuditLog.entity_type == entity_type)
        if date_from is not None:
            query = query.where(AuditLog.created_at >= date_from)
        if date_to is not None:
            query = query.where(AuditLog.created_at <= date_to)
        return query
