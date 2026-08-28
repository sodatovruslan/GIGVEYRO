from __future__ import annotations

from app.core.config import settings
from app.services.exchange_private.bybit import BybitPrivateClient
from app.services.exchange_private.errors import (
    ExchangePrivateAuthenticationError,
    ExchangePrivateError,
    ExchangePrivatePermissionError,
    ExchangePrivateRateLimited,
    ExchangePrivateTimestampError,
)
from app.services.exchange_private.models import ExchangePrivateDiagnostics

_client: BybitPrivateClient | None = None


async def init_exchange_private() -> None:
    global _client  # noqa: PLW0603
    if _client is not None or not settings.BYBIT_PRIVATE_ENABLED:
        return
    _client = BybitPrivateClient(
        base_url=settings.BYBIT_PUBLIC_BASE_URL,
        api_key=settings.BYBIT_API_KEY.get_secret_value(),
        api_secret=settings.BYBIT_API_SECRET.get_secret_value(),
        recv_window_ms=settings.BYBIT_RECV_WINDOW_MS,
        timeout_seconds=settings.BYBIT_PRIVATE_TIMEOUT_SECONDS,
        max_retries=settings.BYBIT_PRIVATE_MAX_RETRIES,
    )


async def close_exchange_private() -> None:
    global _client  # noqa: PLW0603
    if _client is not None:
        await _client.close()
    _client = None


def get_bybit_private_client() -> BybitPrivateClient:
    if _client is None:
        raise RuntimeError("Bybit private read-only runtime is not initialised")
    return _client


async def get_bybit_private_diagnostics() -> dict:
    configured = bool(
        settings.BYBIT_API_KEY.get_secret_value()
        and settings.BYBIT_API_SECRET.get_secret_value()
    )
    if not settings.BYBIT_PRIVATE_ENABLED:
        return _empty_diagnostics(
            configured=configured,
            status="disabled" if configured else "not_configured",
        ).to_dict()
    try:
        client = get_bybit_private_client()
    except RuntimeError:
        return _empty_diagnostics(configured=configured, status="unavailable").to_dict()

    try:
        key_info = await client.get_api_key_info()
        if key_info.permission_safety != "READ_ONLY_SAFE":
            return ExchangePrivateDiagnostics(
                provider="bybit",
                configured=True,
                enabled=True,
                status="over_privileged",
                authentication="valid",
                mode="READ_ONLY",
                permission_safety=key_info.permission_safety,
                masked_key=key_info.masked_key,
                ip_restricted=key_info.ip_restricted,
                expires_at=key_info.expires_at,
                deadline_days=key_info.deadline_days,
                account=None,
                balances=[],
                latency_ms=client.last_latency_ms,
                last_success_at=client.last_success_at,
                rate_limit_remaining=client.rate_limit_remaining,
            ).to_dict()
        account = await client.get_account_info()
        balances = await client.get_balances()
        return ExchangePrivateDiagnostics(
            provider="bybit",
            configured=True,
            enabled=True,
            status="connected",
            authentication="valid",
            mode="READ_ONLY",
            permission_safety=key_info.permission_safety,
            masked_key=key_info.masked_key,
            ip_restricted=key_info.ip_restricted,
            expires_at=key_info.expires_at,
            deadline_days=key_info.deadline_days,
            account=account,
            balances=balances,
            latency_ms=client.last_latency_ms,
            last_success_at=client.last_success_at,
            rate_limit_remaining=client.rate_limit_remaining,
        ).to_dict()
    except ExchangePrivateError as exc:
        return _error_diagnostics(configured, exc).to_dict()


def _empty_diagnostics(*, configured: bool, status: str) -> ExchangePrivateDiagnostics:
    return ExchangePrivateDiagnostics(
        provider="bybit",
        configured=configured,
        enabled=settings.BYBIT_PRIVATE_ENABLED,
        status=status,
        authentication="not_checked",
        mode="READ_ONLY",
        permission_safety="UNKNOWN",
        masked_key=None,
        ip_restricted=None,
        expires_at=None,
        deadline_days=None,
        account=None,
        balances=[],
        latency_ms=None,
        last_success_at=None,
        rate_limit_remaining=None,
    )


def _error_diagnostics(
    configured: bool, exc: ExchangePrivateError
) -> ExchangePrivateDiagnostics:
    if isinstance(exc, ExchangePrivateAuthenticationError):
        status, authentication = "authentication_error", "invalid"
    elif isinstance(exc, ExchangePrivatePermissionError):
        status, authentication = "permission_denied", "valid"
    elif isinstance(exc, ExchangePrivateTimestampError):
        status, authentication = "clock_error", "not_checked"
    elif isinstance(exc, ExchangePrivateRateLimited):
        status, authentication = "rate_limited", "not_checked"
    else:
        status, authentication = "unavailable", "not_checked"
    value = _empty_diagnostics(configured=configured, status=status)
    return ExchangePrivateDiagnostics(
        provider=value.provider,
        configured=value.configured,
        enabled=True,
        status=value.status,
        authentication=authentication,
        mode=value.mode,
        permission_safety=value.permission_safety,
        masked_key=None,
        ip_restricted=None,
        expires_at=None,
        deadline_days=None,
        account=None,
        balances=[],
        latency_ms=_client.last_latency_ms if _client else None,
        last_success_at=_client.last_success_at if _client else None,
        rate_limit_remaining=_client.rate_limit_remaining if _client else None,
    )
