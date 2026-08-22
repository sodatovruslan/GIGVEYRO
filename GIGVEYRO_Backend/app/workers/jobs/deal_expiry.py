"""
Deal Expiry Worker — ARQ job.

Transitions AVAILABLE deals past their TTL to EXPIRED status.

IMPORTANT: EXPIRED status already exists in DealStatus enum.
This job does NOT introduce any new statuses.

Schedule: every 5 minutes via cron (frequent enough to keep state accurate,
but not so frequent as to create DB pressure).

Safety:
  - Idempotent: only transitions deals in AVAILABLE status
  - Uses DB-level time comparison (no clock drift issues)
  - No financial side effects for AVAILABLE→EXPIRED transition
    (AVAILABLE deals have no locked funds)
"""

from __future__ import annotations

import logging

from app.db.session import AsyncSessionLocal
from app.infra.metrics import record_worker_failure, record_worker_success
from app.realtime.contracts import RealtimeEventName
from app.repositories.deal import DealRepository
from app.repositories.realtime import RealtimeOutboxRepository
from app.services.realtime import RealtimeEventService

logger = logging.getLogger(__name__)

JOB_NAME = "deal_expiry"


async def expire_stale_deals(ctx: dict) -> dict:
    """ARQ job: transition AVAILABLE deals past TTL to EXPIRED.

    Args:
        ctx: ARQ context dict.

    Returns:
        dict with expired count.
    """
    job_id = ctx.get("job_id", "unknown")
    attempt = ctx.get("job_try", 1)

    logger.info(
        "event=worker.job.started job=%s job_id=%s attempt=%d",
        JOB_NAME,
        job_id,
        attempt,
    )

    try:
        async with AsyncSessionLocal() as session:
            deals = await DealRepository(session).expire_stale_available()
            realtime = RealtimeEventService(RealtimeOutboxRepository(session))
            for deal in deals:
                await realtime.enqueue_deal(RealtimeEventName.DEAL_EXPIRED, deal)
            await session.commit()

        expired_count = len(deals)
        record_worker_success(JOB_NAME)
        logger.info(
            "event=worker.job.completed job=%s job_id=%s attempt=%d expired=%d",
            JOB_NAME,
            job_id,
            attempt,
            expired_count,
        )
        return {"status": "ok", "expired": expired_count}

    except Exception as exc:
        record_worker_failure(JOB_NAME)
        logger.error(
            "event=worker.job.failed job=%s job_id=%s attempt=%d error=%s",
            JOB_NAME,
            job_id,
            attempt,
            str(exc),
            exc_info=True,
        )
        raise
