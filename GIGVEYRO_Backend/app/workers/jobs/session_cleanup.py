"""
Session/2FA Cleanup Worker — ARQ job.

Deletes expired AuthSession rows (past SESSION_CLEANUP_RETENTION_DAYS) and
expired two_factor_challenges/two_factor_pending_setups rows. These are
already-dead rows by the time this runs (expired_at in the past, or already
revoked) - deleting them is pure housekeeping, no state transitions and no
financial side effects.

Schedule: once per hour is plenty - these tables only ever accumulate
already-unusable rows between runs, nothing depends on prompt deletion.
"""
from __future__ import annotations

import logging

from app.db.session import AsyncSessionLocal
from app.infra.metrics import record_worker_failure, record_worker_success
from app.repositories.account import AccountRepository
from app.repositories.auth_session import AuthSessionRepository
from app.repositories.two_factor import (
    AccountTwoFactorRepository,
    PendingTwoFactorSetupRepository,
    TwoFactorChallengeRepository,
    TwoFactorRecoveryCodeRepository,
)
from app.services.auth import AuthService
from app.services.two_factor import TwoFactorService

logger = logging.getLogger(__name__)

JOB_NAME = "session_cleanup"


async def cleanup_expired_sessions(ctx: dict) -> dict:
    """ARQ job: prune expired auth sessions and expired 2FA challenges/pending setups.

    Args:
        ctx: ARQ context dict.

    Returns:
        dict with counts of rows deleted.
    """
    job_id = ctx.get("job_id", "unknown")
    attempt = ctx.get("job_try", 1)

    logger.info(
        "event=worker.job.started job=%s job_id=%s attempt=%d", JOB_NAME, job_id, attempt
    )

    try:
        async with AsyncSessionLocal() as session:
            auth_service = AuthService(AccountRepository(session), AuthSessionRepository(session))
            sessions_deleted = await auth_service.cleanup_expired_sessions()

            two_factor_service = TwoFactorService(
                AccountTwoFactorRepository(session),
                PendingTwoFactorSetupRepository(session),
                TwoFactorRecoveryCodeRepository(session),
                TwoFactorChallengeRepository(session),
            )
            two_factor_rows_deleted = await two_factor_service.cleanup_expired()

            await session.commit()

        record_worker_success(JOB_NAME)
        logger.info(
            "event=worker.job.completed job=%s job_id=%s attempt=%d "
            "sessions_deleted=%d two_factor_rows_deleted=%d",
            JOB_NAME,
            job_id,
            attempt,
            sessions_deleted,
            two_factor_rows_deleted,
        )
        return {
            "status": "ok",
            "sessions_deleted": sessions_deleted,
            "two_factor_rows_deleted": two_factor_rows_deleted,
        }

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
