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
        Histogram,
        generate_latest,
    )

    _PROMETHEUS_AVAILABLE = True
except ImportError:
    _PROMETHEUS_AVAILABLE = False
    logger.debug("prometheus-client not installed — metrics disabled.")

# ── Metric definitions ─────────────────────────────────────────────────────

if _PROMETHEUS_AVAILABLE:
    # ── Notification Outbox Metrics
    NOTIFICATION_OUTBOX_PENDING = Gauge(
        "gigveyro_notification_outbox_pending",
        "Number of pending notification outbox entries",
    )
    NOTIFICATION_OUTBOX_FAILED = Gauge(
        "gigveyro_notification_outbox_failed",
        "Number of failed notification outbox entries",
    )
    NOTIFICATION_OUTBOX_OLDEST_AGE = Gauge(
        "gigveyro_notification_outbox_oldest_age_seconds",
        "Age of the oldest pending outbox entry in seconds",
    )

    # ── Deposit Scanner Metrics
    DEPOSIT_SCAN_RUNS = Counter(
        "gigveyro_deposit_scan_runs_total",
        "Total deposit scanner runs",
    )
    DEPOSIT_SCAN_ERRORS = Counter(
        "gigveyro_deposit_scan_errors_total",
        "Total deposit scanner errors",
    )
    DEPOSIT_EVENTS_SEEN = Counter(
        "gigveyro_deposit_events_seen_total",
        "Total deposit events seen",
    )
    DEPOSIT_EVENTS_CORRELATED = Counter(
        "gigveyro_deposit_events_correlated_total",
        "Total deposit events correlated",
    )
    DEPOSIT_EVENTS_UNMATCHED = Counter(
        "gigveyro_deposit_events_unmatched_total",
        "Total deposit events unmatched",
    )
    DEPOSIT_SCANNER_REQUESTS = Counter(
        "deposit_scanner_requests_total",
        "Read-only deposit scanner provider request outcomes",
        labelnames=["provider", "status"],
    )
    DEPOSIT_SCANNER_EVENTS = Counter(
        "deposit_scanner_events_total",
        "Deposit scanner provider event normalization outcomes",
        labelnames=["provider", "result"],
    )
    DEPOSIT_SCANNER_LATENCY = Histogram(
        "deposit_scanner_latency_seconds",
        "Deposit scanner provider scan latency",
        labelnames=["provider"],
    )
    DEPOSIT_SCANNER_RATE_LIMITS = Counter(
        "deposit_scanner_rate_limits_total",
        "Deposit scanner provider rate-limit responses",
        labelnames=["provider"],
    )

    # ── Worker & General Metrics
    WORKER_JOBS = Counter(
        "gigveyro_worker_jobs_total",
        "Total background worker job executions",
        labelnames=["job", "status"],  # status: success | failure
    )
    PROVIDER_ERRORS = Counter(
        "gigveyro_provider_errors_total",
        "Total external provider errors",
        labelnames=["provider"],  # e.g. exchange_rate, payout, trongrid
    )
    MARKET_PROVIDER_REQUESTS = Counter(
        "gigveyro_market_provider_requests_total",
        "Public market provider requests",
        labelnames=["provider", "status"],
    )
    MARKET_PROVIDER_LATENCY = Histogram(
        "gigveyro_market_provider_latency_seconds",
        "Public market provider request latency",
        labelnames=["provider"],
    )
    MARKET_PROVIDER_FAILOVERS = Counter(
        "gigveyro_market_provider_failovers_total",
        "Public market provider failovers",
        labelnames=["from_provider", "to_provider"],
    )
    MARKET_PROVIDER_CACHE_HITS = Counter(
        "gigveyro_market_provider_cache_hits_total",
        "Public market provider cache hits",
        labelnames=["provider"],
    )
    MARKET_PROVIDER_QUOTE_AGE = Gauge(
        "gigveyro_market_provider_quote_age_seconds",
        "Age of the latest public market quote",
        labelnames=["provider"],
    )
    FIAT_PROVIDER_REQUESTS = Counter(
        "gigveyro_fiat_provider_requests_total",
        "Fiat provider requests",
        labelnames=["provider", "status"],
    )
    FIAT_PROVIDER_LATENCY = Histogram(
        "gigveyro_fiat_provider_latency_seconds",
        "Fiat provider request latency",
        labelnames=["provider"],
    )
    FIAT_PROVIDER_FAILOVERS = Counter(
        "gigveyro_fiat_provider_failovers_total",
        "Fiat provider failovers",
        labelnames=["from_provider", "to_provider"],
    )
    FIAT_RATE_AGE = Gauge(
        "gigveyro_fiat_rate_age_seconds",
        "Age of the latest fiat quote",
        labelnames=["provider"],
    )
    BUSINESS_RATE_CALCULATIONS = Counter(
        "gigveyro_business_rate_calculations_total",
        "Business exchange-rate calculations",
        labelnames=["mode"],
    )
    BUSINESS_RATE_DEVIATION = Gauge(
        "gigveyro_business_rate_deviation_bps",
        "Deviation between configured fiat providers",
    )
    EXCHANGE_PRIVATE_REQUESTS = Counter(
        "gigveyro_exchange_private_requests_total",
        "Private read-only exchange requests",
        labelnames=["provider", "status"],
    )
    EXCHANGE_PRIVATE_LATENCY = Histogram(
        "gigveyro_exchange_private_latency_seconds",
        "Private read-only exchange request latency",
        labelnames=["provider"],
    )
    EXCHANGE_PRIVATE_AUTH_FAILURES = Counter(
        "gigveyro_exchange_private_auth_failures_total",
        "Private exchange authentication failures",
        labelnames=["provider"],
    )
    EXCHANGE_PRIVATE_RATE_LIMITS = Counter(
        "gigveyro_exchange_private_rate_limits_total",
        "Private exchange rate-limit responses",
        labelnames=["provider"],
    )
    PAYOUT_LIVE_READY = Gauge(
        "gigveyro_payout_live_ready",
        "Whether all future live payout readiness checks pass (network remains disabled)",
    )
    PAYOUT_LIVE_BLOCKERS = Gauge(
        "gigveyro_payout_live_blockers_total",
        "Current live payout readiness blockers",
        labelnames=["reason"],
    )
    TELEGRAM_DELIVERY = Counter(
        "gigveyro_telegram_delivery_total",
        "Telegram delivery outcomes",
        labelnames=["status"],
    )
    TELEGRAM_DELIVERY_LATENCY = Histogram(
        "gigveyro_telegram_delivery_latency_seconds",
        "Telegram sendMessage latency",
    )
    TELEGRAM_CONNECTIONS = Counter(
        "gigveyro_telegram_connections_total",
        "Successful Telegram connection events",
    )
    TELEGRAM_COMMANDS = Counter(
        "gigveyro_telegram_command_total",
        "Telegram command outcomes",
        labelnames=["command", "status"],
    )
else:
    # Stub objects so callers don't need to guard every usage
    class _NoopMetric:
        def inc(self, *a, **kw) -> None: ...
        def dec(self, *a, **kw) -> None: ...
        def set(self, *a, **kw) -> None: ...
        def observe(self, *a, **kw) -> None: ...
        def labels(self, *a, **kw) -> _NoopMetric:
            return self

    NOTIFICATION_OUTBOX_PENDING = _NoopMetric()  # type: ignore[assignment]
    NOTIFICATION_OUTBOX_FAILED = _NoopMetric()  # type: ignore[assignment]
    NOTIFICATION_OUTBOX_OLDEST_AGE = _NoopMetric()  # type: ignore[assignment]
    DEPOSIT_SCAN_RUNS = _NoopMetric()  # type: ignore[assignment]
    DEPOSIT_SCAN_ERRORS = _NoopMetric()  # type: ignore[assignment]
    DEPOSIT_EVENTS_SEEN = _NoopMetric()  # type: ignore[assignment]
    DEPOSIT_EVENTS_CORRELATED = _NoopMetric()  # type: ignore[assignment]
    DEPOSIT_EVENTS_UNMATCHED = _NoopMetric()  # type: ignore[assignment]
    DEPOSIT_SCANNER_REQUESTS = _NoopMetric()  # type: ignore[assignment]
    DEPOSIT_SCANNER_EVENTS = _NoopMetric()  # type: ignore[assignment]
    DEPOSIT_SCANNER_LATENCY = _NoopMetric()  # type: ignore[assignment]
    DEPOSIT_SCANNER_RATE_LIMITS = _NoopMetric()  # type: ignore[assignment]
    WORKER_JOBS = _NoopMetric()  # type: ignore[assignment]
    PROVIDER_ERRORS = _NoopMetric()  # type: ignore[assignment]
    MARKET_PROVIDER_REQUESTS = _NoopMetric()  # type: ignore[assignment]
    MARKET_PROVIDER_LATENCY = _NoopMetric()  # type: ignore[assignment]
    MARKET_PROVIDER_FAILOVERS = _NoopMetric()  # type: ignore[assignment]
    MARKET_PROVIDER_CACHE_HITS = _NoopMetric()  # type: ignore[assignment]
    MARKET_PROVIDER_QUOTE_AGE = _NoopMetric()  # type: ignore[assignment]
    FIAT_PROVIDER_REQUESTS = _NoopMetric()  # type: ignore[assignment]
    FIAT_PROVIDER_LATENCY = _NoopMetric()  # type: ignore[assignment]
    FIAT_PROVIDER_FAILOVERS = _NoopMetric()  # type: ignore[assignment]
    FIAT_RATE_AGE = _NoopMetric()  # type: ignore[assignment]
    BUSINESS_RATE_CALCULATIONS = _NoopMetric()  # type: ignore[assignment]
    BUSINESS_RATE_DEVIATION = _NoopMetric()  # type: ignore[assignment]
    EXCHANGE_PRIVATE_REQUESTS = _NoopMetric()  # type: ignore[assignment]
    EXCHANGE_PRIVATE_LATENCY = _NoopMetric()  # type: ignore[assignment]
    EXCHANGE_PRIVATE_AUTH_FAILURES = _NoopMetric()  # type: ignore[assignment]
    EXCHANGE_PRIVATE_RATE_LIMITS = _NoopMetric()  # type: ignore[assignment]
    PAYOUT_LIVE_READY = _NoopMetric()  # type: ignore[assignment]
    PAYOUT_LIVE_BLOCKERS = _NoopMetric()  # type: ignore[assignment]
    TELEGRAM_DELIVERY = _NoopMetric()  # type: ignore[assignment]
    TELEGRAM_DELIVERY_LATENCY = _NoopMetric()  # type: ignore[assignment]
    TELEGRAM_CONNECTIONS = _NoopMetric()  # type: ignore[assignment]
    TELEGRAM_COMMANDS = _NoopMetric()  # type: ignore[assignment]


# ── FastAPI instrumentator setup ───────────────────────────────────────────


def setup_metrics(app) -> None:  # noqa: ANN001
    """Attach Prometheus HTTP instrumentation and secure /metrics endpoint to the app.

    Call from main.py after creating the FastAPI instance.
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
        ).instrument(app)
        logger.info("Prometheus HTTP request metrics instrumented.")
    except ImportError:
        logger.warning("prometheus-fastapi-instrumentator not installed.")

    from typing import Annotated

    from fastapi import Header, HTTPException, Response, status

    from app.core.config import settings

    @app.get("/metrics", include_in_schema=False)
    async def metrics_endpoint(authorization: Annotated[str | None, Header()] = None) -> Response:
        if not settings.METRICS_ENABLED:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

        if settings.METRICS_AUTH_TOKEN:
            expected = f"Bearer {settings.METRICS_AUTH_TOKEN}"
            if authorization != expected:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Unauthorized metrics access",
                )

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


def record_deposit_scanner_request(provider: str, status: str) -> None:
    DEPOSIT_SCANNER_REQUESTS.labels(provider=provider, status=status).inc()


def record_deposit_scanner_event(provider: str, result: str) -> None:
    DEPOSIT_SCANNER_EVENTS.labels(provider=provider, result=result).inc()


def observe_deposit_scanner_latency(provider: str, latency_seconds: float) -> None:
    DEPOSIT_SCANNER_LATENCY.labels(provider=provider).observe(latency_seconds)


def record_deposit_scanner_rate_limit(provider: str) -> None:
    DEPOSIT_SCANNER_RATE_LIMITS.labels(provider=provider).inc()


def record_provider_error(provider: str) -> None:
    """Record an external provider error."""
    PROVIDER_ERRORS.labels(provider=provider).inc()


def record_market_request(provider: str, status: str, latency_seconds: float) -> None:
    MARKET_PROVIDER_REQUESTS.labels(provider=provider, status=status).inc()
    MARKET_PROVIDER_LATENCY.labels(provider=provider).observe(latency_seconds)


def record_market_failover(from_provider: str, to_provider: str) -> None:
    MARKET_PROVIDER_FAILOVERS.labels(from_provider=from_provider, to_provider=to_provider).inc()


def record_market_cache_hit(provider: str) -> None:
    MARKET_PROVIDER_CACHE_HITS.labels(provider=provider).inc()


def observe_market_quote_age(provider: str, age_seconds: float) -> None:
    MARKET_PROVIDER_QUOTE_AGE.labels(provider=provider).set(age_seconds)


def record_fiat_request(provider: str, status: str, latency_seconds: float) -> None:
    FIAT_PROVIDER_REQUESTS.labels(provider=provider, status=status).inc()
    FIAT_PROVIDER_LATENCY.labels(provider=provider).observe(latency_seconds)


def record_fiat_failover(from_provider: str, to_provider: str) -> None:
    FIAT_PROVIDER_FAILOVERS.labels(from_provider=from_provider, to_provider=to_provider).inc()


def observe_fiat_rate_age(provider: str, age_seconds: float) -> None:
    FIAT_RATE_AGE.labels(provider=provider).set(age_seconds)


def record_business_rate(mode: str) -> None:
    BUSINESS_RATE_CALCULATIONS.labels(mode=mode).inc()


def observe_business_rate_deviation(deviation_bps: float) -> None:
    BUSINESS_RATE_DEVIATION.set(deviation_bps)


def record_exchange_private_request(provider: str, status: str, latency_seconds: float) -> None:
    EXCHANGE_PRIVATE_REQUESTS.labels(provider=provider, status=status).inc()
    EXCHANGE_PRIVATE_LATENCY.labels(provider=provider).observe(latency_seconds)


def record_exchange_private_auth_failure(provider: str) -> None:
    EXCHANGE_PRIVATE_AUTH_FAILURES.labels(provider=provider).inc()


def record_exchange_private_rate_limit(provider: str) -> None:
    EXCHANGE_PRIVATE_RATE_LIMITS.labels(provider=provider).inc()


def observe_live_payout_readiness(ready: bool, all_reasons: list[str], blockers: list[str]) -> None:
    PAYOUT_LIVE_READY.set(1 if ready else 0)
    blocked = set(blockers)
    for reason in all_reasons:
        PAYOUT_LIVE_BLOCKERS.labels(reason=reason).set(1 if reason in blocked else 0)


def set_outbox_pending(count: int) -> None:
    """Update the outbox pending gauge."""
    NOTIFICATION_OUTBOX_PENDING.set(count)


def record_deposit_scan_run() -> None:
    """Record a deposit scanner run."""
    DEPOSIT_SCAN_RUNS.inc()


def record_deposit_events(seen: int, correlated: int, unmatched: int) -> None:
    """Record deposit scan event counts."""
    DEPOSIT_EVENTS_SEEN.inc(seen)
    DEPOSIT_EVENTS_CORRELATED.inc(correlated)
    DEPOSIT_EVENTS_UNMATCHED.inc(unmatched)


def set_outbox_metrics(pending: int, failed: int, oldest_age_seconds: float) -> None:
    """Update outbox pending, failed, and oldest age gauges."""
    NOTIFICATION_OUTBOX_PENDING.set(pending)
    NOTIFICATION_OUTBOX_FAILED.set(failed)
    NOTIFICATION_OUTBOX_OLDEST_AGE.set(oldest_age_seconds)


def record_telegram_delivery(status: str, latency_seconds: float) -> None:
    TELEGRAM_DELIVERY.labels(status=status).inc()
    TELEGRAM_DELIVERY_LATENCY.observe(latency_seconds)


def record_telegram_connection(delta: int) -> None:
    if delta > 0:
        TELEGRAM_CONNECTIONS.inc(delta)


def record_telegram_command(command: str, status: str) -> None:
    TELEGRAM_COMMANDS.labels(command=command, status=status).inc()
