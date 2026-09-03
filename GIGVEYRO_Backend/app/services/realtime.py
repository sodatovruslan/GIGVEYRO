import asyncio
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.enums.account import UserRole
from app.models.deal import Deal
from app.models.deposit import Deposit
from app.models.payout import PayoutIntent
from app.models.realtime import RealtimeOutbox
from app.realtime.broker import RealtimeBroker
from app.realtime.contracts import RealtimeEvent, RealtimeEventName
from app.repositories.realtime import RealtimeOutboxRepository

logger = logging.getLogger(__name__)


class RealtimeEventService:
    def __init__(self, repository: RealtimeOutboxRepository):
        self._repository = repository

    async def enqueue_deal(self, event: RealtimeEventName, deal: Deal) -> RealtimeOutbox:
        account_ids = {deal.merchant_id}
        roles = {UserRole.OWNER}
        if deal.user_id is not None:
            account_ids.add(deal.user_id)
        elif event in (RealtimeEventName.DEAL_CREATED, RealtimeEventName.DEAL_EXPIRED):
            roles.add(UserRole.USER)
        return await self._repository.create(
            RealtimeOutbox(
                event=event.value,
                entity_id=deal.id,
                recipient_account_ids=sorted(str(account_id) for account_id in account_ids),
                recipient_roles=sorted(role.value for role in roles),
                data={"status": deal.status.value},
                occurred_at=datetime.now(UTC),
            )
        )

    async def enqueue_fiat(
        self,
        event: RealtimeEventName,
        *,
        operation_id: uuid.UUID,
        target_account_id: uuid.UUID,
        owner_account_id: uuid.UUID,
        currency: str,
    ) -> RealtimeOutbox:
        if event not in (RealtimeEventName.FIAT_ALLOCATED, RealtimeEventName.FIAT_CONVERTED):
            raise ValueError("Unsupported fiat realtime event")
        return await self._repository.create(
            RealtimeOutbox(
                event=event.value,
                entity_id=operation_id,
                recipient_account_ids=sorted({str(target_account_id), str(owner_account_id)}),
                recipient_roles=[],
                data={"currency": currency},
                occurred_at=datetime.now(UTC),
            )
        )

    async def enqueue_payout(
        self, intent: PayoutIntent, *, withdrawal_id: uuid.UUID
    ) -> tuple[RealtimeOutbox, RealtimeOutbox]:
        recipients = [str(intent.beneficiary_account_id)]
        occurred_at = datetime.now(UTC)
        payout = await self._repository.create(
            RealtimeOutbox(
                event=RealtimeEventName.PAYOUT_UPDATED.value,
                entity_id=intent.id,
                recipient_account_ids=recipients,
                recipient_roles=[UserRole.OWNER.value],
                data={"status": intent.status},
                occurred_at=occurred_at,
            )
        )
        withdrawal = await self._repository.create(
            RealtimeOutbox(
                event=RealtimeEventName.WITHDRAWAL_UPDATED.value,
                entity_id=withdrawal_id,
                recipient_account_ids=recipients,
                recipient_roles=[UserRole.OWNER.value],
                data={"payout_status": intent.status},
                occurred_at=occurred_at,
            )
        )
        return payout, withdrawal

    async def enqueue_deposit_updated(self, deposit: Deposit) -> RealtimeOutbox:
        return await self._repository.create(
            RealtimeOutbox(
                event=RealtimeEventName.DEPOSIT_UPDATED.value,
                entity_id=deposit.id,
                recipient_account_ids=[str(deposit.account_id)],
                recipient_roles=[UserRole.OWNER.value],
                data={"status": deposit.status.value},
                occurred_at=datetime.now(UTC),
            )
        )


class RealtimeOutboxDispatcher:
    def __init__(self, broker: RealtimeBroker):
        self._broker = broker

    async def process_batch(self, session: AsyncSession, limit: int = 100) -> int:
        entries = await RealtimeOutboxRepository(session).pending(limit)
        processed = 0
        for entry in entries:
            entry.attempts += 1
            try:
                event = RealtimeEvent(
                    id=entry.id,
                    event=RealtimeEventName(entry.event),
                    entity_id=entry.entity_id,
                    occurred_at=entry.occurred_at,
                    data=entry.data,
                )
                await self._broker.publish(
                    event,
                    account_ids={uuid.UUID(value) for value in entry.recipient_account_ids},
                    roles={UserRole(value) for value in entry.recipient_roles},
                )
                entry.processed_at = datetime.now(UTC)
                entry.last_error = None
                processed += 1
            except Exception as exc:
                entry.last_error = str(exc)[:1000]
                logger.warning("Realtime outbox delivery failed for %s", entry.id)
        await session.flush()
        return processed

    async def run(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        stop: asyncio.Event,
        poll_interval: float = 0.25,
    ) -> None:
        while not stop.is_set():
            try:
                async with session_factory() as session:
                    await self.process_batch(session)
                    await session.commit()
            except Exception:
                logger.exception("Realtime outbox dispatcher iteration failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=poll_interval)
            except TimeoutError:
                pass
