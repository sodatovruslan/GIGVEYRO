from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.realtime import RealtimeOutbox


class RealtimeOutboxRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, entry: RealtimeOutbox) -> RealtimeOutbox:
        self._session.add(entry)
        await self._session.flush()
        return entry

    async def pending(self, limit: int = 100) -> Sequence[RealtimeOutbox]:
        result = await self._session.execute(
            select(RealtimeOutbox)
            .where(
                RealtimeOutbox.processed_at.is_(None),
                RealtimeOutbox.attempts < RealtimeOutbox.max_attempts,
            )
            .order_by(RealtimeOutbox.occurred_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return result.scalars().all()
