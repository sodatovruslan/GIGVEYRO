import uuid
from datetime import datetime

from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums.deposit import DepositStatus
from app.models.deposit import Deposit, UnmatchedTransfer


class DepositRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_id(self, deposit_id: uuid.UUID) -> Deposit | None:
        return await self._session.get(Deposit, deposit_id)

    async def get_by_id_for_update(self, deposit_id: uuid.UUID) -> Deposit | None:
        result = await self._session.execute(
            select(Deposit).where(Deposit.id == deposit_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_by_tx_hash(self, tx_hash: str) -> Deposit | None:
        result = await self._session.execute(select(Deposit).where(Deposit.tx_hash == tx_hash))
        return result.scalar_one_or_none()

    async def create(self, deposit: Deposit) -> Deposit:
        self._session.add(deposit)
        await self._session.flush()
        await self._session.refresh(deposit)
        return deposit

    async def save(self, deposit: Deposit) -> Deposit:
        await self._session.flush()
        await self._session.refresh(deposit)
        return deposit

    async def create_unmatched_transfer(self, transfer: UnmatchedTransfer) -> UnmatchedTransfer:
        self._session.add(transfer)
        await self._session.flush()
        await self._session.refresh(transfer)
        return transfer

    async def get_unmatched_by_tx_hash(self, tx_hash: str) -> UnmatchedTransfer | None:
        result = await self._session.execute(
            select(UnmatchedTransfer).where(UnmatchedTransfer.tx_hash == tx_hash)
        )
        return result.scalar_one_or_none()

    async def expire_stale_waiting(self) -> None:
        await self._session.execute(
            update(Deposit)
            .where(Deposit.status == DepositStatus.WAITING, Deposit.expires_at <= func.now())
            .values(status=DepositStatus.EXPIRED)
        )

    async def list_for_account(
        self, account_id: uuid.UUID, *, status: DepositStatus | None, limit: int, offset: int
    ) -> list[Deposit]:
        query = select(Deposit).where(Deposit.account_id == account_id)
        if status is not None:
            query = query.where(Deposit.status == status)
        query = query.order_by(Deposit.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def count_for_account(
        self, account_id: uuid.UUID, *, status: DepositStatus | None
    ) -> int:
        query = (
            select(func.count()).select_from(Deposit).where(Deposit.account_id == account_id)
        )
        if status is not None:
            query = query.where(Deposit.status == status)
        result = await self._session.execute(query)
        return result.scalar_one()

    async def list_all(
        self,
        *,
        status: DepositStatus | None,
        account_id: uuid.UUID | None,
        search: str | None,
        tx_hash: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
        limit: int,
        offset: int,
    ) -> list[Deposit]:
        query = self._filtered(
            select(Deposit),
            status=status,
            account_id=account_id,
            search=search,
            tx_hash=tx_hash,
            date_from=date_from,
            date_to=date_to,
        )
        query = query.order_by(Deposit.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def count_all(
        self,
        *,
        status: DepositStatus | None,
        account_id: uuid.UUID | None,
        search: str | None,
        tx_hash: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> int:
        query = self._filtered(
            select(func.count()).select_from(Deposit),
            status=status,
            account_id=account_id,
            search=search,
            tx_hash=tx_hash,
            date_from=date_from,
            date_to=date_to,
        )
        result = await self._session.execute(query)
        return result.scalar_one()

    @staticmethod
    def _filtered(
        query: Select,
        *,
        status: DepositStatus | None,
        account_id: uuid.UUID | None,
        search: str | None,
        tx_hash: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> Select:
        if status is not None:
            query = query.where(Deposit.status == status)
        if account_id is not None:
            query = query.where(Deposit.account_id == account_id)
        if search:
            query = query.where(Deposit.public_id.ilike(f"%{search}%"))
        if tx_hash:
            query = query.where(Deposit.tx_hash == tx_hash)
        if date_from is not None:
            query = query.where(Deposit.created_at >= date_from)
        if date_to is not None:
            query = query.where(Deposit.created_at <= date_to)
        return query
