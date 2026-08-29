import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums.payout import PayoutStatus
from app.models.payout import PayoutApproval, PayoutEvent, PayoutIntent, PayoutPolicy

NON_TERMINAL = (
    PayoutStatus.REQUESTED.value,
    PayoutStatus.RISK_REVIEW.value,
    PayoutStatus.APPROVED.value,
    PayoutStatus.QUEUED.value,
    PayoutStatus.EXECUTION_PENDING.value,
    PayoutStatus.EXECUTING.value,
    PayoutStatus.AWAITING_MANUAL_SETTLEMENT.value,
    PayoutStatus.RECONCILIATION_REQUIRED.value,
)


class PayoutRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def active_policy(self, *, lock: bool = False) -> PayoutPolicy:
        query = select(PayoutPolicy).where(PayoutPolicy.status == "active")
        if lock:
            query = query.with_for_update()
        return (await self.session.execute(query)).scalar_one()

    async def policies_for_update(self) -> list[PayoutPolicy]:
        return list(
            (
                await self.session.execute(
                    select(PayoutPolicy).order_by(PayoutPolicy.version).with_for_update()
                )
            ).scalars()
        )

    async def get_policy(self, policy_id: uuid.UUID) -> PayoutPolicy | None:
        return await self.session.get(PayoutPolicy, policy_id)

    async def save_policy(self, policy: PayoutPolicy) -> PayoutPolicy:
        self.session.add(policy)
        await self.session.flush()
        await self.session.refresh(policy)
        return policy

    async def by_withdrawal(self, withdrawal_id: uuid.UUID) -> PayoutIntent | None:
        return (
            await self.session.execute(
                select(PayoutIntent).where(PayoutIntent.withdrawal_id == withdrawal_id)
            )
        ).scalar_one_or_none()

    async def get(self, intent_id: uuid.UUID, *, lock: bool = False) -> PayoutIntent | None:
        query = select(PayoutIntent).where(PayoutIntent.id == intent_id)
        if lock:
            query = query.with_for_update()
        return (await self.session.execute(query)).scalar_one_or_none()

    async def add_intent(self, intent: PayoutIntent) -> PayoutIntent:
        self.session.add(intent)
        await self.session.flush()
        await self.session.refresh(intent)
        return intent

    async def save_intent(self, intent: PayoutIntent) -> PayoutIntent:
        await self.session.flush()
        await self.session.refresh(intent)
        return intent

    async def approval(self, intent_id: uuid.UUID, approver_id: uuid.UUID) -> PayoutApproval | None:
        return (
            await self.session.execute(
                select(PayoutApproval).where(
                    PayoutApproval.payout_intent_id == intent_id,
                    PayoutApproval.approver_account_id == approver_id,
                )
            )
        ).scalar_one_or_none()

    async def add_approval(self, approval: PayoutApproval) -> PayoutApproval:
        self.session.add(approval)
        await self.session.flush()
        return approval

    async def approval_count(self, intent_id: uuid.UUID) -> int:
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(PayoutApproval)
                .where(
                    PayoutApproval.payout_intent_id == intent_id,
                    PayoutApproval.decision == "approved",
                )
            )
            or 0
        )

    async def approvals(self, intent_id: uuid.UUID) -> list[PayoutApproval]:
        return list(
            (
                await self.session.execute(
                    select(PayoutApproval)
                    .where(PayoutApproval.payout_intent_id == intent_id)
                    .order_by(PayoutApproval.created_at)
                )
            ).scalars()
        )

    async def event(
        self,
        intent_id: uuid.UUID,
        name: str,
        actor_id: uuid.UUID | None = None,
        metadata: dict | None = None,
    ) -> PayoutEvent:
        entry = PayoutEvent(
            payout_intent_id=intent_id,
            event=name,
            actor_account_id=actor_id,
            event_metadata=metadata or {},
        )
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def events(self, intent_id: uuid.UUID) -> list[PayoutEvent]:
        return list(
            (
                await self.session.execute(
                    select(PayoutEvent)
                    .where(PayoutEvent.payout_intent_id == intent_id)
                    .order_by(PayoutEvent.created_at)
                )
            ).scalars()
        )

    async def list_intents(
        self, *, status: str | None, limit: int, offset: int
    ) -> tuple[list[PayoutIntent], int]:
        where = [] if status is None else [PayoutIntent.status == status]
        items = list(
            (
                await self.session.execute(
                    select(PayoutIntent)
                    .where(*where)
                    .order_by(PayoutIntent.created_at.desc())
                    .limit(limit)
                    .offset(offset)
                )
            ).scalars()
        )
        total = await self.session.scalar(
            select(func.count()).select_from(PayoutIntent).where(*where)
        )
        return items, int(total or 0)

    async def next_queued(self, limit: int = 25) -> list[PayoutIntent]:
        return list(
            (
                await self.session.execute(
                    select(PayoutIntent)
                    .where(PayoutIntent.status == PayoutStatus.QUEUED.value)
                    .order_by(PayoutIntent.queued_at)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).scalars()
        )

    async def exposure(self, *, asset: str = "USDT") -> dict[str, Decimal]:
        now = datetime.now(UTC)

        async def total(statuses: tuple[str, ...], since: datetime | None = None) -> Decimal:
            query = select(func.coalesce(func.sum(PayoutIntent.amount), 0)).where(
                PayoutIntent.asset == asset, PayoutIntent.status.in_(statuses)
            )
            if since:
                query = query.where(PayoutIntent.executed_at >= since)
            return Decimal(await self.session.scalar(query) or 0)

        return {
            "pending": await total(NON_TERMINAL),
            "daily": await total((PayoutStatus.SUCCEEDED.value,), now - timedelta(days=1)),
            "hourly": await total((PayoutStatus.SUCCEEDED.value,), now - timedelta(hours=1)),
        }
