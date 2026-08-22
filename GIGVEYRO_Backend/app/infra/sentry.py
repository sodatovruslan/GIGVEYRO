"""
Optional Sentry SDK integration for GIGVEYRO.

Activates only when SENTRY_DSN is configured.
If SENTRY_DSN is empty/unset, this module is a no-op — the application
will NOT fail to start due to missing Sentry configuration.

Usage (call once at startup in main.py lifespan):
    from app.infra.sentry import init_sentry
    init_sentry()
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def init_sentry() -> None:
    """Initialise Sentry SDK if SENTRY_DSN is configured.

    Safe to call unconditionally — gracefully handles:
    - Missing SENTRY_DSN
    - sentry-sdk not installed
    """
    from app.core.config import settings

    dsn = getattr(settings, "SENTRY_DSN", "")
    if not dsn:
        logger.debug("SENTRY_DSN not configured — Sentry disabled.")
        return

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

        sentry_sdk.init(
            dsn=dsn,
            environment=settings.APP_ENV,
            # Performance tracing — adjust sample_rate for production traffic volume
            traces_sample_rate=float(getattr(settings, "SENTRY_TRACES_SAMPLE_RATE", "0.1")),
            integrations=[
                FastApiIntegration(),
                SqlalchemyIntegration(),
            ],
            # Strip PII from events automatically
            send_default_pii=False,
            # Ignore expected non-error exceptions
            ignore_errors=[
                KeyboardInterrupt,
                SystemExit,
            ],
        )
        logger.info(
            "Sentry initialised: env=%s, dsn=***configured***",
            settings.APP_ENV,
        )
    except ImportError:
        logger.warning(
            "sentry-sdk not installed. "
            "Add sentry-sdk to requirements.txt to enable error monitoring."
        )
    except Exception as exc:  # noqa: BLE001
        # Never crash startup due to Sentry configuration issues
        logger.error("Sentry initialisation failed (non-fatal): %s", exc)
