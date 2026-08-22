"""
Deposit Scanner Worker — ARQ job (READ-ONLY).

Periodically calls DepositService.scan_and_correlate_deposits() which:
  - Scans blockchain via the configured provider (TronGrid or mock)
  - Correlates on-chain transfers with active deposit intents
  - Records unmatched/ambiguous transfers safely

STRICT SAFETY RULES:
  - READ-ONLY provider calls only (fetch_recent_transactions)
  - NO private keys, NO transaction signing, NO fund movement
  - Provider in mock mode → safe no-op (no blockchain calls)
  - Idempotent: duplicate tx_hash is rejected by DB unique constraint
  - Uses distributed lock to prevent concurrent scanner runs

Schedule: every SCAN_INTERVAL_SECONDS (default 60s via cron).
"""
from __future__ import annotations

import logging

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.infra.metrics import (
    record_deposit_scan_error,
    record_worker_failure,
    record_worker_success,
)
from app.infra.redis_client import get_redis
from app.repositories.account import AccountRepository
from app.repositories.deposit import DepositRepository
from app.repositories.ledger import LedgerRepository
from app.repositories.notification import NotificationRepository
from app.repositories.telegram import TelegramLinkRepository
from app.repositories.wallet import WalletRepository
from app.services.deposit import DepositService
from app.services.notification import NotificationService
from app.services.provider_factory import get_deposit_provider
from app.services.telegram_provider import MockTelegramProvider
from app.services.wallet import WalletService
from app.workers.distributed_lock import DistributedLock

logger = logging.getLogger(__name__)

JOB_NAME = "deposit_scanner"
LOCK_NAME = "deposit_scanner_singleton"
# Lock TTL = scan interval + 10s buffer, in milliseconds
LOCK_TTL_MS = (settings.SCAN_INTERVAL_SECONDS + 10) * 1000


async def scan_deposits(ctx: dict) -> dict:
    """ARQ job: scan blockchain for new deposits (read-only).

    Args:
        ctx: ARQ context (contains 'redis' key from ARQ).

    Returns:
        dict with scan result summary.
    """
    job_id = ctx.get("job_id", "unknown")
    attempt = ctx.get("job_try", 1)

    logger.info(
        "event=worker.job.started job=%s job_id=%s attempt=%d",
        JOB_NAME,
        job_id,
        attempt,
    )

    from app.infra.metrics import record_deposit_scan_run

    record_deposit_scan_run()

    if settings.DEPOSIT_PROVIDER_TYPE == "mock":
        logger.info(
            "event=worker.job.completed job=%s job_id=%s attempt=%d status=skipped reason=mock_provider",
            JOB_NAME,
            job_id,
            attempt,
        )
        return {"status": "skipped", "reason": "mock_provider"}

    redis = get_redis()

    async with DistributedLock(redis, LOCK_NAME, ttl_ms=LOCK_TTL_MS) as acquired:
        if not acquired:
            logger.info(
                "event=worker.job.completed job=%s job_id=%s attempt=%d status=skipped reason=lock_held",
                JOB_NAME,
                job_id,
                attempt,
            )
            return {"status": "skipped", "reason": "lock_held"}

        return await _run_scan(job_id, attempt)


async def _run_scan(job_id: str, attempt: int) -> dict:
    """Execute the deposit scan within the distributed lock."""
    provider = get_deposit_provider()
    deposit_address = provider.get_deposit_address()

    try:
        async with AsyncSessionLocal() as session:
            account_repo = AccountRepository(session)
            wallet_service = WalletService(
                WalletRepository(session),
                LedgerRepository(session),
                account_repo,
            )
            notification_service = NotificationService(
                NotificationRepository(session),
                TelegramLinkRepository(session),
                MockTelegramProvider(),
            )
            service = DepositService(
                deposit_repository=DepositRepository(session),
                account_repository=account_repo,
                wallet_service=wallet_service,
                provider=provider,
                notification_service=notification_service,
            )
            processed = await service.scan_and_correlate_deposits()

        record_worker_success(JOB_NAME)
        logger.info(
            "event=worker.job.completed job=%s job_id=%s attempt=%d processed=%d address=%s",
            JOB_NAME,
            job_id,
            attempt,
            processed,
            deposit_address,
        )
        return {"status": "ok", "processed": processed}

    except Exception as exc:
        record_deposit_scan_error()
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

