"""
ARQ Worker Settings for GIGVEYRO.

ARQ (Async Redis Queue) — chosen for:
  - Native asyncio (no gevent/threading hacks)
  - Redis-backed queue (same Redis we use for rate limiting)
  - Cron scheduling built-in
  - Simple, minimal dependencies
  - Production-proven for FastAPI/SQLAlchemy stacks
  - SIGTERM-aware graceful shutdown

Worker Architecture:
  - process_notification_outbox : every OUTBOX_POLL_INTERVAL_SECONDS (default 30s)
  - scan_deposits               : every SCAN_INTERVAL_SECONDS (default 60s)
  - expire_stale_deals          : every 5 minutes
  - process_approved_payouts    : every 10 minutes (NO-OP when PAYOUT_ENABLED=False)

WebSocket Note:
  The ARQ worker runs in a SEPARATE process from the FastAPI web server.
  It does NOT share InMemoryRealtimeBroker state with the web process.
  This is intentional — workers handle background I/O, not real-time events.
  Real-time events triggered by worker jobs (e.g. deposit confirmed) should
  be written to the realtime outbox table, which the web process polls.
"""
from __future__ import annotations

from arq import cron
from arq.connections import RedisSettings

from app.core.config import settings
from app.workers.jobs.deal_expiry import expire_stale_deals
from app.workers.jobs.deposit_scanner import scan_deposits
from app.workers.jobs.notification_outbox import process_notification_outbox
from app.workers.jobs.payout_orchestrator import process_approved_payouts


def _redis_settings() -> RedisSettings:
    """Parse REDIS_URL into ARQ RedisSettings."""
    from urllib.parse import urlparse

    parsed = urlparse(settings.REDIS_URL)
    db_index = int(parsed.path.lstrip("/") or 0)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        password=parsed.password,
        database=db_index,
    )


async def _heartbeat_loop(redis_client) -> None:
    import asyncio
    import logging
    logger = logging.getLogger("worker.heartbeat")
    key = f"{settings.REDIS_KEY_PREFIX}:worker:heartbeat"
    while True:
        try:
            await redis_client.set(key, "alive", ex=60)
        except Exception as exc:
            logger.warning("Failed to write worker heartbeat: %s", exc)
        await asyncio.sleep(15)


async def startup(ctx: dict) -> None:
    """ARQ worker startup hook — initialise shared resources."""
    import asyncio
    import logging

    from app.infra.logging_config import configure_logging
    from app.infra.redis_client import get_redis, init_redis
    from app.infra.sentry import init_sentry

    configure_logging(app_env=settings.APP_ENV, log_level="INFO")
    logger = logging.getLogger("worker.startup")

    init_sentry()
    await init_redis()

    redis_client = get_redis()
    if redis_client:
        ctx["heartbeat_task"] = asyncio.create_task(_heartbeat_loop(redis_client))

    logger.info(
        "ARQ worker started: env=%s, concurrency=%d",
        settings.APP_ENV,
        settings.WORKER_CONCURRENCY,
    )


async def shutdown(ctx: dict) -> None:
    """ARQ worker shutdown hook — clean up shared resources."""
    import logging

    from app.infra.redis_client import close_redis

    logger = logging.getLogger("worker.shutdown")

    task = ctx.get("heartbeat_task")
    if task:
        task.cancel()
        try:
            await task
        except Exception:
            pass

    await close_redis()
    logger.info("ARQ worker shut down cleanly.")


class WorkerSettings:
    """ARQ worker configuration.

    ARQ reads this class by convention when running:
        arq app.workers.arq_settings.WorkerSettings
    """

    # Redis connection for ARQ job queue
    redis_settings = _redis_settings()

    # Registered job functions
    functions = [
        process_notification_outbox,
        scan_deposits,
        expire_stale_deals,
        process_approved_payouts,
    ]

    # Cron schedule definitions
    cron_jobs = [
        cron(
            process_notification_outbox,
            second={0, 30},  # every 30 seconds
            unique=True,
        ),
        cron(
            scan_deposits,
            second={0},
            minute={0, 1},  # every minute (ARQ cron granularity is minute-based)
            unique=True,
        ),
        cron(
            expire_stale_deals,
            minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55},  # every 5 minutes
            second={0},
            unique=True,
        ),
        cron(
            process_approved_payouts,
            minute={0, 10, 20, 30, 40, 50},  # every 10 minutes
            second={0},
            unique=True,
        ),
    ]

    # Job concurrency — keep low for financial safety
    max_jobs = settings.WORKER_CONCURRENCY

    # Lifecycle hooks
    on_startup = startup
    on_shutdown = shutdown

    # Graceful shutdown: finish current job before exiting on SIGTERM
    handle_signals = True

    # Job timeout — kill stuck jobs after 5 minutes
    job_timeout = 300

    # Retry failed jobs with exponential backoff (max 3 retries)
    max_tries = 3
    keep_result = 60  # Keep job results in Redis for 60 seconds
