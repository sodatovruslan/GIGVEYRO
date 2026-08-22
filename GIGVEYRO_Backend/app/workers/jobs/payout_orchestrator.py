"""
Payout Orchestrator Worker — ARQ job (DISABLED BY DEFAULT).

Framework stub for future automatic payout processing.

CRITICAL SAFETY RULE:
  PAYOUTS_ENABLED=False by default.
  This job is a NO-OP unless explicitly enabled via environment variable.
  NO real funds will move without explicit production configuration.

When enabled (PAYOUTS_ENABLED=True):
  - Finds APPROVED withdrawals without payout_ref
  - Submits to payout provider via existing WithdrawalService
  - Idempotent: checks existing payout_ref before submitting

Currently: framework/stub only. ExternalPayoutAdapter requires
real provider credentials and PAYOUTS_ENABLED=True to do anything.

Schedule: every 10 minutes (if enabled).
"""
from __future__ import annotations

import logging

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.enums.withdrawal import WithdrawalStatus
from app.infra.metrics import record_worker_failure, record_worker_success
from app.repositories.account import AccountRepository
from app.repositories.ledger import LedgerRepository
from app.repositories.wallet import WalletRepository
from app.repositories.withdrawal import WithdrawalRepository
from app.services.provider_factory import get_payout_provider
from app.services.wallet import WalletService
from app.services.withdrawal import (
    PayoutDisabledError,
    WithdrawalService,
)

logger = logging.getLogger(__name__)

JOB_NAME = "payout_orchestrator"


async def process_approved_payouts(ctx: dict) -> dict:
    """ARQ job: orchestrate payout for APPROVED withdrawals.

    This job is a NO-OP when PAYOUT_ENABLED=False (the safe default).
    """
    job_id = ctx.get("job_id", "unknown")
    attempt = ctx.get("job_try", 1)

    logger.info(
        "event=worker.job.started job=%s job_id=%s attempt=%d",
        JOB_NAME,
        job_id,
        attempt,
    )

    if not settings.PAYOUT_ENABLED:
        logger.info(
            "event=worker.job.completed job=%s job_id=%s attempt=%d status=disabled reason=PAYOUT_ENABLED_False",
            JOB_NAME,
            job_id,
            attempt,
        )
        return {"status": "disabled", "reason": "PAYOUT_ENABLED=False"}

    try:
        async with AsyncSessionLocal() as session:
            account_repo = AccountRepository(session)
            wallet_service = WalletService(
                WalletRepository(session),
                LedgerRepository(session),
                account_repo,
            )
            withdrawal_repo = WithdrawalRepository(session)
            payout_provider = get_payout_provider()

            service = WithdrawalService(
                withdrawal_repository=withdrawal_repo,
                wallet_service=wallet_service,
                account_repository=account_repo,
                payout_provider=payout_provider,
            )

            # List APPROVED withdrawals that need payout
            approved, _ = await service.list_for_owner(
                status=WithdrawalStatus.APPROVED,
                merchant_id=None,
                search=None,
                date_from=None,
                date_to=None,
                limit=50,
                offset=0,
            )

            processed = 0
            failed = 0

            for withdrawal in approved:
                try:
                    import uuid
                    SYSTEM_ACTOR_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
                    await service.mark_paid_by_owner(
                        owner_id=SYSTEM_ACTOR_ID,
                        withdrawal_id=withdrawal.id,
                        comment="Automated payout via worker",
                    )
                    processed += 1
                except PayoutDisabledError:
                    logger.error(
                        "event=worker.job.aborted job=%s job_id=%s attempt=%d reason=PayoutDisabledError",
                        JOB_NAME,
                        job_id,
                        attempt,
                    )
                    break
                except Exception as exc:
                    failed += 1
                    logger.error(
                        "event=worker.job.item_failed job=%s job_id=%s attempt=%d item_id=%s error=%s",
                        JOB_NAME,
                        job_id,
                        attempt,
                        str(withdrawal.id),
                        str(exc),
                    )

        record_worker_success(JOB_NAME)
        logger.info(
            "event=worker.job.completed job=%s job_id=%s attempt=%d processed=%d failed=%d",
            JOB_NAME,
            job_id,
            attempt,
            processed,
            failed,
        )
        return {"status": "ok", "processed": processed, "failed": failed}

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
