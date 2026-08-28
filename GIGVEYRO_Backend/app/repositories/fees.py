import uuid
from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fees import FeePolicy, FeeSnapshot, OwnerProfitEntry


class FeeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def active_policy(self, *, lock: bool = False) -> FeePolicy:
        query = select(FeePolicy).where(FeePolicy.status == "active")
        if lock:
            query = query.with_for_update(read=True)
        result = await self.session.execute(query)
        return result.scalar_one()

    async def policy_by_id(self, policy_id: uuid.UUID, *, lock: bool = False) -> FeePolicy | None:
        query = select(FeePolicy).where(FeePolicy.id == policy_id)
        if lock:
            query = query.with_for_update()
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def create_policy(self, policy: FeePolicy) -> FeePolicy:
        self.session.add(policy)
        await self.session.flush()
        await self.session.refresh(policy)
        return policy

    async def lock_all_policies(self) -> list[FeePolicy]:
        result = await self.session.execute(
            select(FeePolicy).order_by(FeePolicy.version).with_for_update()
        )
        return list(result.scalars().all())

    async def save_policy(self, policy: FeePolicy) -> FeePolicy:
        await self.session.flush()
        await self.session.refresh(policy)
        return policy

    async def flush(self) -> None:
        await self.session.flush()

    async def create_snapshot(self, snapshot: FeeSnapshot) -> FeeSnapshot:
        self.session.add(snapshot)
        await self.session.flush()
        await self.session.refresh(snapshot)
        return snapshot

    async def create_profit(self, entry: OwnerProfitEntry) -> OwnerProfitEntry:
        self.session.add(entry)
        await self.session.flush()
        await self.session.refresh(entry)
        return entry

    async def list_profit_entries(
        self,
        *,
        date_from: datetime | None,
        date_to: datetime | None,
        fee_type: str | None,
        currency: str | None,
        source_type: str | None,
        source_id: uuid.UUID | None,
        limit: int,
        offset: int,
    ) -> tuple[list[OwnerProfitEntry], int]:
        filters = self._profit_filters(
            date_from=date_from,
            date_to=date_to,
            fee_type=fee_type,
            currency=currency,
            source_type=source_type,
            source_id=source_id,
        )
        query: Select = select(OwnerProfitEntry).where(*filters)
        count_query = select(func.count()).select_from(OwnerProfitEntry).where(*filters)
        result = await self.session.execute(
            query.order_by(OwnerProfitEntry.created_at.desc()).limit(limit).offset(offset)
        )
        count = await self.session.scalar(count_query)
        return list(result.scalars().all()), int(count or 0)

    async def profit_summary(self, since: datetime | None) -> list[tuple]:
        query = select(
            OwnerProfitEntry.currency,
            OwnerProfitEntry.fee_type,
            func.sum(OwnerProfitEntry.gross_amount),
            func.sum(OwnerProfitEntry.fee_amount),
            func.count(OwnerProfitEntry.id),
            func.avg(OwnerProfitEntry.fee_amount),
        )
        if since is not None:
            query = query.where(OwnerProfitEntry.created_at >= since)
        result = await self.session.execute(
            query.group_by(OwnerProfitEntry.currency, OwnerProfitEntry.fee_type)
        )
        return list(result.all())

    @staticmethod
    def _profit_filters(
        *,
        date_from: datetime | None,
        date_to: datetime | None,
        fee_type: str | None,
        currency: str | None,
        source_type: str | None,
        source_id: uuid.UUID | None,
    ) -> list:
        filters = []
        if date_from is not None:
            filters.append(OwnerProfitEntry.created_at >= date_from)
        if date_to is not None:
            filters.append(OwnerProfitEntry.created_at <= date_to)
        if fee_type is not None:
            filters.append(OwnerProfitEntry.fee_type == fee_type)
        if currency is not None:
            filters.append(OwnerProfitEntry.currency == currency)
        if source_type is not None:
            filters.append(OwnerProfitEntry.source_type == source_type)
        if source_id is not None:
            filters.append(OwnerProfitEntry.source_id == source_id)
        return filters
