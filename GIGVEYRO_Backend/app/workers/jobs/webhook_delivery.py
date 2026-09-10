"""
Webhook Delivery Worker — ARQ job.

Periodically polls pending WebhookDelivery rows (written synchronously by
DepositService._credit() when an invoice is paid - see
WebhookService.enqueue_delivery) and POSTs each one to the merchant's
configured URL, signed with an HMAC-SHA256 of the raw body using the
webhook's decrypted secret.

Retries failed/unreachable deliveries with exponential backoff up to
WebhookDelivery.max_attempts, then marks them FAILED. Uses the same
row-lock + skip_locked outbox pattern as the realtime dispatcher.

Schedule: every 30s via cron (app/workers/arq_settings.py).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.enums.webhook import WebhookDeliveryStatus, WebhookStatus
from app.infra.metrics import record_worker_failure, record_worker_success
from app.infra.redis_client import get_redis
from app.models.webhook import WebhookDelivery
from app.repositories.webhook import WebhookDeliveryRepository, WebhookRepository
from app.services.webhook import WebhookService
from app.workers.distributed_lock import DistributedLock

logger = logging.getLogger(__name__)

JOB_NAME = "webhook_delivery"
LOCK_NAME = "webhook_delivery_singleton"
LOCK_TTL_MS = 30_000
_REQUEST_TIMEOUT_SECONDS = 5.0
_RESPONSE_SNIPPET_MAX_CHARS = 500
_ERROR_SNIPPET_MAX_CHARS = 500
_SIGNATURE_HEADER = "X-GigaPay-Signature"


def _backoff_seconds(attempts: int) -> int:
    # 1st retry after 30s, then 2m, 8m, 32m - bounded, no jitter needed at
    # this volume (a handful of deliveries per merchant event, not a
    # high-throughput queue).
    return min(30 * (4 ** max(attempts - 1, 0)), 3600)


async def deliver_webhooks(ctx: dict) -> dict:
    job_id = ctx.get("job_id", "unknown")
    attempt = ctx.get("job_try", 1)
    logger.info(
        "event=worker.job.started job=%s job_id=%s attempt=%d", JOB_NAME, job_id, attempt
    )

    redis = get_redis()
    async with DistributedLock(redis, LOCK_NAME, ttl_ms=LOCK_TTL_MS) as acquired:
        if not acquired:
            logger.info(
                "event=worker.job.completed job=%s job_id=%s attempt=%d "
                "status=skipped reason=lock_held",
                JOB_NAME,
                job_id,
                attempt,
            )
            return {"status": "skipped", "reason": "lock_held"}

        try:
            async with AsyncSessionLocal() as session:
                processed = await _process_batch(session)
                await session.commit()
            record_worker_success(JOB_NAME)
            logger.info(
                "event=worker.job.completed job=%s job_id=%s attempt=%d processed=%d",
                JOB_NAME,
                job_id,
                attempt,
                processed,
            )
            return {"status": "ok", "processed": processed}
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


async def _process_batch(session: AsyncSession) -> int:
    delivery_repo = WebhookDeliveryRepository(session)
    webhook_repo = WebhookRepository(session)
    service = WebhookService(webhook_repo, delivery_repo)

    deliveries = await delivery_repo.pending(limit=50)
    if not deliveries:
        return 0

    processed = 0
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
        for delivery in deliveries:
            await _deliver_one(client, webhook_repo, service, delivery_repo, delivery)
            processed += 1
    return processed


async def _deliver_one(
    client: httpx.AsyncClient,
    webhook_repo: WebhookRepository,
    service: WebhookService,
    delivery_repo: WebhookDeliveryRepository,
    delivery: WebhookDelivery,
) -> None:
    webhook = await webhook_repo.get_by_id(delivery.webhook_id)
    delivery.attempts += 1

    if webhook is None or webhook.status != WebhookStatus.ACTIVE:
        delivery.status = WebhookDeliveryStatus.FAILED
        delivery.last_error = "webhook no longer exists or is disabled"
        await delivery_repo.save(delivery)
        return

    body = json.dumps(
        {"event": delivery.event_type, "data": delivery.payload}, separators=(",", ":")
    ).encode("utf-8")
    secret = service.decrypt_secret(webhook)
    signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    try:
        response = await client.post(
            webhook.url,
            content=body,
            headers={
                "Content-Type": "application/json",
                _SIGNATURE_HEADER: f"sha256={signature}",
            },
        )
        delivery.last_response_status = response.status_code
        delivery.last_response_snippet = response.text[:_RESPONSE_SNIPPET_MAX_CHARS]
        if 200 <= response.status_code < 300:
            delivery.status = WebhookDeliveryStatus.SUCCESS
            delivery.delivered_at = datetime.now(UTC)
        else:
            delivery.last_error = f"unexpected status {response.status_code}"
            _schedule_retry_or_fail(delivery)
    except httpx.RequestError as exc:
        delivery.last_error = str(exc)[:_ERROR_SNIPPET_MAX_CHARS]
        _schedule_retry_or_fail(delivery)

    await delivery_repo.save(delivery)


def _schedule_retry_or_fail(delivery: WebhookDelivery) -> None:
    if delivery.attempts >= delivery.max_attempts:
        delivery.status = WebhookDeliveryStatus.FAILED
        delivery.next_attempt_at = None
    else:
        delivery.next_attempt_at = datetime.now(UTC) + timedelta(
            seconds=_backoff_seconds(delivery.attempts)
        )
