"""
ARQ Worker Entrypoint for GIGVEYRO.

Run this file to start the background worker process:
    python worker_entrypoint.py

In Docker (see docker-compose.yml worker service):
    command: python worker_entrypoint.py

Environment:
    All config is read from environment variables or .env file.
    REDIS_URL must point to the shared Redis instance.
    DATABASE_URL must point to the shared PostgreSQL instance.

Worker jobs:
    - process_notification_outbox  (every 30s)
    - scan_deposits                (every 60s, read-only)
    - expire_stale_deals           (every 5min)
    - process_approved_payouts     (every 10min, NO-OP unless PAYOUT_ENABLED=True)

Scaling:
    Run multiple worker processes for concurrency.
    Each job uses distributed locks to prevent duplicate execution.
    WORKER_CONCURRENCY controls max concurrent jobs per process.

Safety:
    PAYOUT_ENABLED=False by default. No real funds moved without explicit enable.
    Deposit scanner is read-only — no private keys, no signing.
"""
import logging

# Ensure app/ is importable when running from GIGVEYRO_Backend/
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app.core.config import settings  # noqa: E402
from app.infra.logging_config import configure_logging  # noqa: E402

# Configure logging immediately so all imports log correctly
configure_logging(app_env=settings.APP_ENV, log_level="INFO")

logger = logging.getLogger("worker_entrypoint")


def main() -> None:
    """Start the ARQ worker process."""
    import arq

    logger.info(
        "Starting GIGVEYRO ARQ worker | env=%s | redis=%s",
        settings.APP_ENV,
        settings.REDIS_URL.split("@")[-1],  # Never log credentials
    )

    # ARQ CLI runner
    arq.run_worker_main()


if __name__ == "__main__":
    # When run as: python worker_entrypoint.py
    # Pass WorkerSettings class path to ARQ
    sys.argv = ["arq", "app.workers.arq_settings.WorkerSettings"]
    main()
