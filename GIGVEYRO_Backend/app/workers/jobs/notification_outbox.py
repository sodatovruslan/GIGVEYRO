"""
Notification Outbox Worker — ARQ job.

Wraps the existing NotificationService.process_outbox_batch() method.
Does NOT rewrite notification business logic (Claude #1 zone).

Schedule: every OUTBOX_POLL_INTERVAL_SECONDS (default 30s via cron).

Guarantees:
  - Max attempts / dead-letter state managed by NotificationService itself.
  - Idempotent: already-processed entries are skipped by status filter.
  - No real money involved.

Telegram is fail-closed while disabled. When explicitly enabled, the worker uses
the async aiogram provider in every environment; tests inject a mock provider.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import func, select

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.enums.notification import NotificationStatus
from app.infra.metrics import record_worker_failure, record_worker_success, set_outbox_metrics
from app.models.notification import NotificationOutbox
from app.repositories.notification import NotificationRepository
from app.repositories.telegram import TelegramLinkRepository
from app.services.notification import NotificationService
from app.services.telegram_provider import get_telegram_provider

logger = logging.getLogger(__name__)

JOB_NAME = "notification_outbox"


async def process_notification_outbox(ctx: dict) -> dict:
    """ARQ job: process a batch of pending notification outbox entries.

    Args:
        ctx: ARQ context dict (contains 'redis' key from ARQ).

    Returns:
        dict with processed count and job outcome.
    """
    job_id = ctx.get("job_id", "unknown")
    attempt = ctx.get("job_try", 1)

    logger.info(
        "event=worker.job.started job=%s job_id=%s attempt=%d",
        JOB_NAME,
        job_id,
        attempt,
    )

    batch_size = settings.OUTBOX_BATCH_SIZE

    if not settings.TELEGRAM_BOT_ENABLED or not settings.TELEGRAM_DELIVERY_ENABLED:
        return {"processed": 0, "pending_approx": 0, "status": "disabled"}

    try:
        async with AsyncSessionLocal() as session:
            notification_repo = NotificationRepository(session)
            telegram_repo = TelegramLinkRepository(session)
            telegram_provider = get_telegram_provider()

            service = NotificationService(
                notification_repo=notification_repo,
                telegram_repo=telegram_repo,
                telegram_provider=telegram_provider,
            )

            processed = await service.process_outbox_batch(limit=batch_size)

            # Measure pending depth, failed, and oldest age for observability
            res_pending = await session.execute(
                select(func.count(NotificationOutbox.id)).where(
                    NotificationOutbox.status == NotificationStatus.PENDING
                )
            )
            pending_count = res_pending.scalar_one() or 0

            res_failed = await session.execute(
                select(func.count(NotificationOutbox.id)).where(
                    NotificationOutbox.status == NotificationStatus.FAILED
                )
            )
            failed_count = res_failed.scalar_one() or 0

            res_oldest = await session.execute(
                select(NotificationOutbox.created_at)
                .where(NotificationOutbox.status == NotificationStatus.PENDING)
                .order_by(NotificationOutbox.created_at.asc())
                .limit(1)
            )
            oldest_created_at = res_oldest.scalar_one_or_none()
            oldest_age = 0.0
            if oldest_created_at:
                if oldest_created_at.tzinfo is None:
                    oldest_created_at = oldest_created_at.replace(tzinfo=UTC)
                oldest_age = (datetime.now(UTC) - oldest_created_at).total_seconds()

            set_outbox_metrics(pending_count, failed_count, oldest_age)
            await session.commit()

        record_worker_success(JOB_NAME)
        logger.info(
            "event=worker.job.completed job=%s job_id=%s attempt=%d "
            "processed=%d pending_approx=%d failed=%d oldest_age=%d",
            JOB_NAME,
            job_id,
            attempt,
            processed,
            pending_count,
            failed_count,
            int(oldest_age),
        )
        return {"processed": processed, "pending_approx": pending_count, "status": "ok"}

    except Exception as exc:
        record_worker_failure(JOB_NAME)
        logger.error(
            "event=worker.job.failed job=%s job_id=%s attempt=%d error_category=%s",
            JOB_NAME,
            job_id,
            attempt,
            type(exc).__name__,
            exc_info=True,
        )
        raise  # ARQ will handle retry
