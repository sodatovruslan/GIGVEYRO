import uuid
from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums.wallet import LedgerEntryType
from app.models.ledger import LedgerEntry


class LedgerRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, entry: LedgerEntry) -> LedgerEntry:
        # Append-only: there is deliberately no update()/delete() here.
        self._session.add(entry)
        await self._session.flush()
        await self._session.refresh(entry)
        return entry

    async def get_by_wallet_and_idempotency_key(
        self, wallet_id: uuid.UUID, idempotency_key: str
    ) -> LedgerEntry | None:
        result = await self._session.execute(
            select(LedgerEntry).where(
                LedgerEntry.wallet_id == wallet_id,
                LedgerEntry.idempotency_key == idempotency_key,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_account(
        self,
        *,
        account_id: uuid.UUID,
        entry_type: LedgerEntryType | None,
        date_from: datetime | None,
        date_to: datetime | None,
        limit: int,
        offset: int,
    ) -> list[LedgerEntry]:
        query = self._filtered_query(
            select(LedgerEntry),
            account_id=account_id,
            entry_type=entry_type,
            date_from=date_from,
            date_to=date_to,
        )
        query = query.order_by(LedgerEntry.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def count_for_account(
        self,
        *,
        account_id: uuid.UUID,
        entry_type: LedgerEntryType | None,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> int:
        query = self._filtered_query(
            select(func.count()).select_from(LedgerEntry),
            account_id=account_id,
            entry_type=entry_type,
            date_from=date_from,
            date_to=date_to,
        )
        result = await self._session.execute(query)
        return result.scalar_one()

    @staticmethod
    def _filtered_query(
        query: Select,
        *,
        account_id: uuid.UUID,
        entry_type: LedgerEntryType | None,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> Select:
        query = query.where(LedgerEntry.account_id == account_id)
        if entry_type is not None:
            query = query.where(LedgerEntry.type == entry_type)
        if date_from is not None:
            query = query.where(LedgerEntry.created_at >= date_from)
        if date_to is not None:
            query = query.where(LedgerEntry.created_at <= date_to)
        return query
