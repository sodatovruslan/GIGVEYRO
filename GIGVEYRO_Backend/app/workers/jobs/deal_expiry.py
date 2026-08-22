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
from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.enums.deal import DealStatus
from app.infra.metrics import record_worker_failure, record_worker_success
from app.models.deal import Deal

logger = logging.getLogger(__name__)

JOB_NAME = "deal_expiry"


async def expire_stale_deals(ctx: dict) -> dict:
    """ARQ job: transition AVAILABLE deals past TTL to EXPIRED.

    Args:
        ctx: ARQ context dict.

    Returns:
        dict with expired count.
    """
    expiry_cutoff = datetime.now(UTC) - timedelta(minutes=settings.DEAL_TTL_MINUTES)
    logger.info(
        "deal_expiry: expiring AVAILABLE deals created before %s (TTL=%d min)",
        expiry_cutoff.isoformat(),
        settings.DEAL_TTL_MINUTES,
    )

    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                update(Deal)
                .where(
                    Deal.status == DealStatus.AVAILABLE,
                    Deal.created_at < expiry_cutoff,
                )
                .values(
                    status=DealStatus.EXPIRED,
                    updated_at=datetime.now(UTC),
                )
                .returning(Deal.id)
            )
            await session.commit()
            expired_ids = result.fetchall()

        expired_count = len(expired_ids)
        record_worker_success(JOB_NAME)
        logger.info("deal_expiry: expired %d deals.", expired_count)
        return {"status": "ok", "expired": expired_count}

    except Exception as exc:
        record_worker_failure(JOB_NAME)
        logger.error("deal_expiry: job failed: %s", exc, exc_info=True)
        raise
