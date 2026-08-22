import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, select

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.enums.account import UserRole
from app.enums.deal import DealStatus
from app.models.account import Account
from app.models.deal import Deal
from app.models.realtime import RealtimeOutbox
from app.realtime.contracts import RealtimeEventName
from app.services.deal import generate_public_id
from app.workers.jobs.deal_expiry import expire_stale_deals


async def test_deal_expiry_job_is_idempotent_and_enqueues_realtime_event():
    merchant_id = uuid.uuid4()
    deal_id = uuid.uuid4()
    async with AsyncSessionLocal() as session:
        session.add(
            Account(
                id=merchant_id,
                username=f"expiry_{uuid.uuid4().hex[:8]}",
                password_hash=hash_password("ExpiryTestPassword123"),
                role=UserRole.MERCHANT,
                full_name="Expiry Test Merchant",
                is_active=True,
            )
        )
        session.add(
            Deal(
                id=deal_id,
                public_id=generate_public_id(),
                merchant_id=merchant_id,
                amount_tjs=Decimal("100"),
                status=DealStatus.AVAILABLE,
                expires_at=datetime.now(UTC) - timedelta(minutes=1),
            )
        )
        await session.commit()

    try:
        first = await expire_stale_deals({"job_id": "expiry-test", "job_try": 1})
        second = await expire_stale_deals({"job_id": "expiry-test-rerun", "job_try": 1})

        assert first == {"status": "ok", "expired": 1}
        assert second == {"status": "ok", "expired": 0}

        async with AsyncSessionLocal() as session:
            deal = await session.get(Deal, deal_id)
            events = list(
                (
                    await session.execute(
                        select(RealtimeOutbox).where(RealtimeOutbox.entity_id == deal_id)
                    )
                )
                .scalars()
                .all()
            )
            assert deal is not None and deal.status == DealStatus.EXPIRED
            assert len(events) == 1
            assert events[0].event == RealtimeEventName.DEAL_EXPIRED.value
            assert events[0].recipient_account_ids == [str(merchant_id)]
            assert events[0].recipient_roles == [UserRole.OWNER.value, UserRole.USER.value]
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(delete(RealtimeOutbox).where(RealtimeOutbox.entity_id == deal_id))
            await session.execute(delete(Deal).where(Deal.id == deal_id))
            await session.execute(delete(Account).where(Account.id == merchant_id))
            await session.commit()
