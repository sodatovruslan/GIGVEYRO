"""
Tests for background worker configuration and safety.

Tests:
  - Production config rejects PAYOUT_ENABLED=True + mock provider
  - PAYOUTS_ENABLED=False is safe (no-op)
  - Payout orchestrator job is disabled by default
  - Deposit scanner skips mock provider
  - Worker settings reference valid job functions
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import Settings


class TestProductionConfigValidation:
    """Production settings validation rules."""

    def test_payout_enabled_with_mock_provider_rejected_in_production(self):
        """Production must reject PAYOUT_ENABLED=True with mock payout provider."""
        with pytest.raises(ValueError, match="PAYOUT_ENABLED=True with PAYOUT_PROVIDER_TYPE=mock"):
            Settings(
                DATABASE_URL="postgresql+asyncpg://user:pass@db/test",
                JWT_SECRET_KEY="a-very-long-jwt-secret-key-minimum-32chars",
                APP_ENV="production",
                DEBUG=False,
                CORS_ALLOWED_ORIGINS=["https://example.com"],
                DEPOSIT_PROVIDER_TYPE="trongrid",
                PAYOUT_ENABLED=True,
                PAYOUT_PROVIDER_TYPE="mock",
                ALLOW_MOCK_PROVIDERS_IN_PRODUCTION=False,
            )

    def test_payout_enabled_with_real_provider_allowed_in_production(self):
        """Production allows PAYOUT_ENABLED=True when using a real provider."""
        # Should not raise
        s = Settings(
            DATABASE_URL="postgresql+asyncpg://user:pass@db/test",
            JWT_SECRET_KEY="a-very-long-jwt-secret-key-minimum-32chars",
            APP_ENV="production",
            DEBUG=False,
            CORS_ALLOWED_ORIGINS=["https://example.com"],
            DEPOSIT_PROVIDER_TYPE="trongrid",
            PAYOUT_ENABLED=True,
            PAYOUT_PROVIDER_TYPE="external_adapter",
            ALLOW_MOCK_PROVIDERS_IN_PRODUCTION=False,
            PAYOUT_API_KEY="real-key",
            PAYOUT_API_URL="https://api.payout.real",
        )
        assert s.PAYOUT_ENABLED is True

    def test_payout_enabled_false_is_always_safe(self):
        """PAYOUT_ENABLED=False is always safe regardless of provider."""
        s = Settings(
            DATABASE_URL="postgresql+asyncpg://user:pass@db/test",
            JWT_SECRET_KEY="a-very-long-jwt-secret-key-minimum-32chars",
            APP_ENV="production",
            DEBUG=False,
            CORS_ALLOWED_ORIGINS=["https://example.com"],
            DEPOSIT_PROVIDER_TYPE="trongrid",
            PAYOUT_ENABLED=False,
            PAYOUT_PROVIDER_TYPE="mock",
            ALLOW_MOCK_PROVIDERS_IN_PRODUCTION=False,
        )
        assert s.PAYOUT_ENABLED is False

    def test_debug_true_rejected_in_production(self):
        """DEBUG=True is rejected in production."""
        with pytest.raises(ValueError, match="DEBUG must be False"):
            Settings(
                DATABASE_URL="postgresql+asyncpg://user:pass@db/test",
                JWT_SECRET_KEY="a-very-long-jwt-secret-key-minimum-32chars",
                APP_ENV="production",
                DEBUG=True,
            )

    def test_weak_jwt_key_rejected_in_production(self):
        """Short/default JWT key is rejected in production."""
        with pytest.raises(ValueError, match="JWT_SECRET_KEY must be strong"):
            Settings(
                DATABASE_URL="postgresql+asyncpg://user:pass@db/test",
                JWT_SECRET_KEY="CHANGE_ME",
                APP_ENV="production",
                DEBUG=False,
            )

    def test_wildcard_cors_rejected_in_production(self):
        """Wildcard CORS origin is rejected in production."""
        with pytest.raises(ValueError, match="Wildcard CORS origins"):
            Settings(
                DATABASE_URL="postgresql+asyncpg://user:pass@db/test",
                JWT_SECRET_KEY="a-very-long-jwt-secret-key-minimum-32chars",
                APP_ENV="production",
                DEBUG=False,
                CORS_ALLOWED_ORIGINS=["*"],
            )

    def test_production_rejects_mock_deposit_provider(self):
        """Production rejects a mock deposit provider unless explicitly allowed."""
        with pytest.raises(
            ValueError, match="DEPOSIT_PROVIDER_TYPE=mock is forbidden in production"
        ):
            Settings(
                DATABASE_URL="postgresql+asyncpg://user:pass@db/test",
                JWT_SECRET_KEY="a-very-long-jwt-secret-key-minimum-32chars",
                APP_ENV="production",
                DEBUG=False,
                DEPOSIT_PROVIDER_TYPE="mock",
                ALLOW_MOCK_PROVIDERS_IN_PRODUCTION=False,
            )

    def test_production_rejects_horizontal_inmemory_broker(self):
        """Production rejects horizontal scaling (WEB_CONCURRENCY > 1) with inmemory broker."""
        with pytest.raises(
            ValueError, match="REALTIME_BROKER must be set to 'redis' in production"
        ):
            Settings(
                DATABASE_URL="postgresql+asyncpg://user:pass@db/test",
                JWT_SECRET_KEY="a-very-long-jwt-secret-key-minimum-32chars",
                APP_ENV="production",
                DEBUG=False,
                DEPOSIT_PROVIDER_TYPE="trongrid",
                REALTIME_BROKER="inmemory",
                WEB_CONCURRENCY=2,
            )

    def test_production_rejects_enabled_payout_missing_credentials(self):
        """Production rejects PAYOUT_ENABLED=True with missing provider credentials."""
        with pytest.raises(
            ValueError, match="PAYOUT_ENABLED=True requires real payout provider settings"
        ):
            Settings(
                DATABASE_URL="postgresql+asyncpg://user:pass@db/test",
                JWT_SECRET_KEY="a-very-long-jwt-secret-key-minimum-32chars",
                APP_ENV="production",
                DEBUG=False,
                DEPOSIT_PROVIDER_TYPE="trongrid",
                PAYOUT_ENABLED=True,
                PAYOUT_PROVIDER_TYPE="external_adapter",
                PAYOUT_API_KEY="",  # missing key
                ALLOW_MOCK_PROVIDERS_IN_PRODUCTION=False,
            )


class TestPayoutOrchestratorSafety:
    """Payout orchestrator job is disabled by default."""

    async def test_payout_orchestrator_noop_when_disabled(self):
        """process_approved_payouts returns disabled status when PAYOUT_ENABLED=False."""
        from app.workers.jobs.payout_orchestrator import process_approved_payouts

        with patch("app.workers.jobs.payout_orchestrator.settings") as mock_settings:
            mock_settings.PAYOUT_ENABLED = False

            result = await process_approved_payouts(ctx={})

        assert result["status"] == "disabled"
        assert result["reason"] == "PAYOUT_ENABLED=False"


class TestDepositScannerSafety:
    """Deposit scanner skips when provider is mock."""

    async def test_deposit_scanner_skips_mock_provider(self):
        """scan_deposits returns skipped when DEPOSIT_PROVIDER_TYPE=mock."""
        from app.workers.jobs.deposit_scanner import scan_deposits

        with patch("app.workers.jobs.deposit_scanner.settings") as mock_settings:
            mock_settings.DEPOSIT_PROVIDER_TYPE = "mock"

            result = await scan_deposits(ctx={})

        assert result["status"] == "skipped"
        assert result["reason"] == "mock_provider"

    async def test_deposit_scanner_commits_processed_results(self):
        """The worker persists the service transaction before closing its session."""
        from app.workers.jobs.deposit_scanner import _run_scan

        session = MagicMock()
        session.commit = AsyncMock()
        session_context = MagicMock()
        session_context.__aenter__ = AsyncMock(return_value=session)
        session_context.__aexit__ = AsyncMock(return_value=None)

        provider = MagicMock()
        provider.get_deposit_address.return_value = "test-deposit-address"
        service = MagicMock()
        service.scan_and_correlate_deposits = AsyncMock(return_value=2)

        with (
            patch(
                "app.workers.jobs.deposit_scanner.AsyncSessionLocal",
                return_value=session_context,
            ),
            patch(
                "app.workers.jobs.deposit_scanner.get_deposit_provider",
                return_value=provider,
            ),
            patch("app.workers.jobs.deposit_scanner.DepositService", return_value=service),
        ):
            result = await _run_scan("scanner-test", 1)

        assert result == {"status": "ok", "processed": 2}
        session.commit.assert_awaited_once()


class TestWorkerSettings:
    """ARQ WorkerSettings is importable and has required attributes."""

    def test_worker_settings_importable(self):
        """WorkerSettings can be imported without errors."""
        from app.workers.arq_settings import WorkerSettings

        assert hasattr(WorkerSettings, "functions")
        assert hasattr(WorkerSettings, "cron_jobs")
        assert hasattr(WorkerSettings, "on_startup")
        assert hasattr(WorkerSettings, "on_shutdown")

    def test_worker_settings_has_all_jobs(self):
        """WorkerSettings registers all expected jobs."""
        from app.workers.arq_settings import WorkerSettings
        from app.workers.jobs.deal_expiry import expire_stale_deals
        from app.workers.jobs.deposit_scanner import scan_deposits
        from app.workers.jobs.notification_outbox import process_notification_outbox
        from app.workers.jobs.payout_orchestrator import process_approved_payouts

        assert process_notification_outbox in WorkerSettings.functions
        assert scan_deposits in WorkerSettings.functions
        assert expire_stale_deals in WorkerSettings.functions
        assert process_approved_payouts in WorkerSettings.functions

    async def test_worker_shutdown_cancels_heartbeat_cleanly(self):
        """Worker shutdown treats heartbeat cancellation as normal lifecycle."""
        from app.workers.arq_settings import shutdown

        heartbeat = asyncio.create_task(asyncio.sleep(60))
        with patch("app.infra.redis_client.close_redis") as close_redis:
            await shutdown({"heartbeat_task": heartbeat})

        assert heartbeat.cancelled()
        close_redis.assert_awaited_once()
