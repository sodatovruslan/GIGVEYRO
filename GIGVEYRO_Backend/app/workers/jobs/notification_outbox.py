"""
Notification Outbox Worker — ARQ job.

Wraps the existing NotificationService.process_outbox_batch() method.
Does NOT rewrite notification business logic (Claude #1 zone).

Schedule: every OUTBOX_POLL_INTERVAL_SECONDS (default 30s via cron).

Guarantees:
  - Max attempts / dead-letter state managed by NotificationService itself.
  - Idempotent: already-processed entries are skipped by status filter.
  - No real money involved.

Telegram provider: uses MockTelegramProvider in development.
For production Telegram, configure TELEGRAM_BOT_TOKEN and use a real provider.
"""
from __future__ import annotations

import logging

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.infra.metrics import record_worker_failure, record_worker_success, set_outbox_pending
from app.repositories.notification import NotificationRepository
from app.repositories.telegram import TelegramLinkRepository
from app.services.notification import NotificationService
from app.services.telegram_provider import MockTelegramProvider

logger = logging.getLogger(__name__)

JOB_NAME = "notification_outbox"


def _get_telegram_provider() -> MockTelegramProvider:
    """Return the configured Telegram provider.

    Currently returns MockTelegramProvider.
    Replace with a real provider when TELEGRAM_BOT_TOKEN is configured.
    """
    # TODO: When Claude #1 implements real Telegram provider,
    # switch based on settings.TELEGRAM_PROVIDER_TYPE here.
    return MockTelegramProvider()


async def process_notification_outbox(ctx: dict) -> dict:
    """ARQ job: process a batch of pending notification outbox entries.

    Args:
        ctx: ARQ context dict (contains 'redis' key from ARQ).

    Returns:
        dict with processed count and job outcome.
    """
    batch_size = settings.OUTBOX_BATCH_SIZE
    logger.info("notification_outbox: starting batch (limit=%d)", batch_size)

    try:
        async with AsyncSessionLocal() as session:
            notification_repo = NotificationRepository(session)
            telegram_repo = TelegramLinkRepository(session)
            telegram_provider = _get_telegram_provider()

            service = NotificationService(
                notification_repo=notification_repo,
                telegram_repo=telegram_repo,
                telegram_provider=telegram_provider,
            )

            processed = await service.process_outbox_batch(limit=batch_size)

            # Measure pending depth for observability
            pending_entries = await notification_repo.get_pending_outbox_entries(limit=1000)
            pending_count = len(pending_entries)
            set_outbox_pending(pending_count)

        record_worker_success(JOB_NAME)
        logger.info(
            "notification_outbox: processed=%d, pending_approx=%d",
            processed,
            pending_count,
        )
        return {"processed": processed, "pending_approx": pending_count, "status": "ok"}

    except Exception as exc:
        record_worker_failure(JOB_NAME)
        logger.error("notification_outbox: job failed: %s", exc, exc_info=True)
        raise  # ARQ will handle retry
