import hashlib
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums.deposit import (
    CorrelationStatus,
    DepositAsset,
    DepositStatus,
    ReconciliationStatus,
)
from app.models.deposit import Deposit, DepositReconciliationAction, UnmatchedTransfer


class DepositRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    @property
    def session(self) -> AsyncSession:
        return self._session

    async def lock_reconciliation_idempotency(
        self, actor_account_id: uuid.UUID, idempotency_key: str
    ) -> None:
        digest = hashlib.sha256(f"{actor_account_id}:{idempotency_key}".encode()).digest()
        lock_id = int.from_bytes(digest[:8], "big", signed=True)
        await self._session.execute(select(func.pg_advisory_xact_lock(lock_id)))

    async def get_by_id(self, deposit_id: uuid.UUID) -> Deposit | None:
        return await self._session.get(Deposit, deposit_id)

    async def get_by_id_for_update(self, deposit_id: uuid.UUID) -> Deposit | None:
        result = await self._session.execute(
            select(Deposit).where(Deposit.id == deposit_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_by_tx_hash(self, tx_hash: str) -> Deposit | None:
        result = await self._session.execute(
            select(Deposit).where(Deposit.tx_hash == tx_hash).limit(1)
        )
        return result.scalar_one_or_none()

    async def get_legacy_by_tx_hash(self, tx_hash: str) -> Deposit | None:
        result = await self._session.execute(
            select(Deposit)
            .where(
                Deposit.tx_hash == tx_hash,
                or_(
                    Deposit.provider_event_id.is_(None),
                    Deposit.provider_event_id.like("legacy:%"),
                ),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_by_provider_event_id(self, provider_event_id: str) -> Deposit | None:
        result = await self._session.execute(
            select(Deposit).where(Deposit.provider_event_id == provider_event_id)
        )
        return result.scalar_one_or_none()

    async def get_by_invoice_id(self, invoice_id: uuid.UUID) -> Deposit | None:
        result = await self._session.execute(
            select(Deposit).where(Deposit.invoice_id == invoice_id)
        )
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
            select(UnmatchedTransfer).where(UnmatchedTransfer.tx_hash == tx_hash).limit(1)
        )
        return result.scalar_one_or_none()

    async def get_legacy_unmatched_by_tx_hash(self, tx_hash: str) -> UnmatchedTransfer | None:
        result = await self._session.execute(
            select(UnmatchedTransfer)
            .where(
                UnmatchedTransfer.tx_hash == tx_hash,
                UnmatchedTransfer.provider_event_id.like("legacy:%"),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_unmatched_by_provider_event_id(
        self, provider_event_id: str
    ) -> UnmatchedTransfer | None:
        result = await self._session.execute(
            select(UnmatchedTransfer).where(
                UnmatchedTransfer.provider_event_id == provider_event_id
            )
        )
        return result.scalar_one_or_none()

    async def get_unmatched_by_provider_event_id_for_update(
        self, provider_event_id: str
    ) -> UnmatchedTransfer | None:
        result = await self._session.execute(
            select(UnmatchedTransfer)
            .where(UnmatchedTransfer.provider_event_id == provider_event_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_unmatched_by_id(self, transfer_id: uuid.UUID) -> UnmatchedTransfer | None:
        return await self._session.get(UnmatchedTransfer, transfer_id)

    async def get_unmatched_by_id_for_update(
        self, transfer_id: uuid.UUID
    ) -> UnmatchedTransfer | None:
        result = await self._session.execute(
            select(UnmatchedTransfer).where(UnmatchedTransfer.id == transfer_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def save_unmatched(self, transfer: UnmatchedTransfer) -> UnmatchedTransfer:
        await self._session.flush()
        await self._session.refresh(transfer)
        return transfer

    async def list_reconciliation_candidates(self, transfer: UnmatchedTransfer) -> list[Deposit]:
        query = (
            select(Deposit)
            .where(
                Deposit.status == DepositStatus.WAITING,
                Deposit.asset == DepositAsset.USDT,
                Deposit.network == transfer.network,
                Deposit.deposit_address == transfer.to_address,
                Deposit.expires_at > func.now(),
            )
            .order_by((Deposit.expected_amount == transfer.amount).desc(), Deposit.created_at.asc())
            .limit(50)
        )
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def get_reconciliation_action(
        self, actor_account_id: uuid.UUID, idempotency_key: str
    ) -> DepositReconciliationAction | None:
        result = await self._session.execute(
            select(DepositReconciliationAction).where(
                DepositReconciliationAction.actor_account_id == actor_account_id,
                DepositReconciliationAction.idempotency_key == idempotency_key,
            )
        )
        return result.scalar_one_or_none()

    async def create_reconciliation_action(
        self, action: DepositReconciliationAction
    ) -> DepositReconciliationAction:
        self._session.add(action)
        await self._session.flush()
        await self._session.refresh(action)
        return action

    async def list_reconciliation_actions(
        self, transfer_id: uuid.UUID
    ) -> list[DepositReconciliationAction]:
        result = await self._session.execute(
            select(DepositReconciliationAction)
            .where(DepositReconciliationAction.transfer_id == transfer_id)
            .order_by(DepositReconciliationAction.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_unmatched(
        self,
        *,
        correlation_status: CorrelationStatus | None,
        reconciliation_status: ReconciliationStatus | None,
        tx_hash: str | None,
        reason: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
        min_amount: Decimal | None,
        max_amount: Decimal | None,
        limit: int,
        offset: int,
    ) -> list[UnmatchedTransfer]:
        query = self._filtered_unmatched(
            select(UnmatchedTransfer),
            correlation_status=correlation_status,
            reconciliation_status=reconciliation_status,
            tx_hash=tx_hash,
            reason=reason,
            date_from=date_from,
            date_to=date_to,
            min_amount=min_amount,
            max_amount=max_amount,
        )
        query = query.order_by(UnmatchedTransfer.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def count_unmatched(
        self,
        *,
        correlation_status: CorrelationStatus | None,
        reconciliation_status: ReconciliationStatus | None,
        tx_hash: str | None,
        reason: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
        min_amount: Decimal | None,
        max_amount: Decimal | None,
    ) -> int:
        query = self._filtered_unmatched(
            select(func.count()).select_from(UnmatchedTransfer),
            correlation_status=correlation_status,
            reconciliation_status=reconciliation_status,
            tx_hash=tx_hash,
            reason=reason,
            date_from=date_from,
            date_to=date_to,
            min_amount=min_amount,
            max_amount=max_amount,
        )
        result = await self._session.execute(query)
        return result.scalar_one()

    @staticmethod
    def _filtered_unmatched(
        query: Select,
        *,
        correlation_status: CorrelationStatus | None,
        reconciliation_status: ReconciliationStatus | None,
        tx_hash: str | None,
        reason: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
        min_amount: Decimal | None,
        max_amount: Decimal | None,
    ) -> Select:
        if correlation_status is not None:
            query = query.where(UnmatchedTransfer.correlation_status == correlation_status)
        if reconciliation_status is not None:
            query = query.where(UnmatchedTransfer.reconciliation_status == reconciliation_status)
        if tx_hash:
            query = query.where(UnmatchedTransfer.tx_hash.ilike(f"%{tx_hash}%"))
        if reason:
            query = query.where(UnmatchedTransfer.reason.ilike(f"%{reason}%"))
        if date_from is not None:
            query = query.where(UnmatchedTransfer.created_at >= date_from)
        if date_to is not None:
            query = query.where(UnmatchedTransfer.created_at <= date_to)
        if min_amount is not None:
            query = query.where(UnmatchedTransfer.amount >= min_amount)
        if max_amount is not None:
            query = query.where(UnmatchedTransfer.amount <= max_amount)
        return query

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
        query = select(func.count()).select_from(Deposit).where(Deposit.account_id == account_id)
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
