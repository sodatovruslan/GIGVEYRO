"""Controlled payout worker. Disabled by default and simulation-only."""

import logging

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.enums.payout import PayoutProviderMode
from app.infra.metrics import record_worker_failure, record_worker_success
from app.repositories.payout import PayoutRepository
from app.services.payout_runtime import build_controlled_payout_service

logger = logging.getLogger(__name__)
JOB_NAME = "payout_orchestrator"


async def process_approved_payouts(ctx: dict) -> dict:
    """Process locked queued simulator intents; no live provider can be selected."""
    job_id = ctx.get("job_id", "unknown")
    if not settings.PAYOUT_ENABLED:
        return {"status": "disabled", "reason": "PAYOUT_ENABLED=False"}
    if (
        settings.PAYOUT_PROVIDER_MODE != PayoutProviderMode.SIMULATED.value
        or not settings.PAYOUT_SIMULATION_ENABLED
    ):
        return {"status": "disabled", "reason": "simulation disabled"}
    processed = failed = 0
    try:
        async with AsyncSessionLocal() as session:
            repo = PayoutRepository(session)
            service = build_controlled_payout_service(session)
            intents = await repo.next_queued()
            for intent in intents:
                try:
                    await service.execute(intent.id)
                    processed += 1
                except Exception as exc:
                    failed += 1
                    logger.error(
                        "event=worker.job.item_failed job=%s job_id=%s item_id=%s error=%s",
                        JOB_NAME,
                        job_id,
                        intent.id,
                        type(exc).__name__,
                    )
            await session.commit()
        record_worker_success(JOB_NAME)
        return {"status": "ok", "processed": processed, "failed": failed}
    except Exception:
        record_worker_failure(JOB_NAME)
        raise
