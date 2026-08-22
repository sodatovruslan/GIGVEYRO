"""
Prometheus metrics foundation for GIGVEYRO.

Provides:
  - HTTP request metrics via prometheus-fastapi-instrumentator (if installed)
  - Custom application-level gauges / counters:
      gigveyro_outbox_pending_total    — notification outbox queue depth
      gigveyro_worker_jobs_total       — worker job outcomes (success/fail)
      gigveyro_deposit_scan_errors_total — deposit scanner provider errors
      gigveyro_provider_errors_total   — integration provider failures

/metrics endpoint is registered in main.py.
If prometheus-client is not installed, the module is a no-op.

NOTE: No high-cardinality UUID labels are used in any metric.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ── Attempt to import prometheus libraries ─────────────────────────────────

try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        REGISTRY,
        Counter,
        Gauge,
        generate_latest,
    )

    _PROMETHEUS_AVAILABLE = True
except ImportError:
    _PROMETHEUS_AVAILABLE = False
    logger.debug("prometheus-client not installed — metrics disabled.")

# ── Metric definitions ─────────────────────────────────────────────────────

if _PROMETHEUS_AVAILABLE:
    OUTBOX_PENDING = Gauge(
        "gigveyro_outbox_pending_total",
        "Number of pending notification outbox entries",
    )

    WORKER_JOBS = Counter(
        "gigveyro_worker_jobs_total",
        "Total background worker job executions",
        labelnames=["job", "status"],  # status: success | failure
    )

    DEPOSIT_SCAN_ERRORS = Counter(
        "gigveyro_deposit_scan_errors_total",
        "Total deposit scanner provider errors",
    )

    PROVIDER_ERRORS = Counter(
        "gigveyro_provider_errors_total",
        "Total external provider errors",
        labelnames=["provider"],  # e.g. exchange_rate, payout, trongrid
    )
else:
    # Stub objects so callers don't need to guard every usage
    class _NoopMetric:
        def inc(self, *a, **kw) -> None: ...
        def dec(self, *a, **kw) -> None: ...
        def set(self, *a, **kw) -> None: ...
        def labels(self, *a, **kw) -> _NoopMetric:
            return self

    OUTBOX_PENDING = _NoopMetric()  # type: ignore[assignment]
    WORKER_JOBS = _NoopMetric()  # type: ignore[assignment]
    DEPOSIT_SCAN_ERRORS = _NoopMetric()  # type: ignore[assignment]
    PROVIDER_ERRORS = _NoopMetric()  # type: ignore[assignment]


# ── FastAPI instrumentator setup ───────────────────────────────────────────

def setup_metrics(app) -> None:  # noqa: ANN001
    """Attach Prometheus HTTP instrumentation and /metrics endpoint to the app.

    Call from main.py after creating the FastAPI instance.
    Safe no-op if prometheus-fastapi-instrumentator is not installed.
    """
    if not _PROMETHEUS_AVAILABLE:
        logger.info("Prometheus metrics disabled (prometheus-client not installed).")
        return

    try:
        from prometheus_fastapi_instrumentator import Instrumentator

        Instrumentator(
            should_group_status_codes=True,
            should_ignore_untemplated=True,
            should_respect_env_var=False,
            should_instrument_requests_inprogress=True,
            excluded_handlers=["/metrics", "/health/*"],
            # No high-cardinality labels
            inprogress_labels=False,
        ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

        logger.info("Prometheus metrics enabled at /metrics")
    except ImportError:
        # Expose a basic /metrics endpoint using prometheus_client directly
        logger.info(
            "prometheus-fastapi-instrumentator not installed — "
            "exposing basic /metrics with prometheus_client."
        )
        from fastapi import Response

        @app.get("/metrics", include_in_schema=False)
        async def metrics_endpoint() -> Response:
            return Response(
                content=generate_latest(REGISTRY),
                media_type=CONTENT_TYPE_LATEST,
            )


def record_worker_success(job_name: str) -> None:
    """Record a successful worker job execution."""
    WORKER_JOBS.labels(job=job_name, status="success").inc()


def record_worker_failure(job_name: str) -> None:
    """Record a failed worker job execution."""
    WORKER_JOBS.labels(job=job_name, status="failure").inc()


def record_deposit_scan_error() -> None:
    """Record a deposit scanner provider error."""
    DEPOSIT_SCAN_ERRORS.inc()


def record_provider_error(provider: str) -> None:
    """Record an external provider error."""
    PROVIDER_ERRORS.labels(provider=provider).inc()


def set_outbox_pending(count: int) -> None:
    """Update the outbox pending gauge."""
    OUTBOX_PENDING.set(count)
