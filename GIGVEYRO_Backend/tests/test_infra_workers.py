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

from unittest.mock import AsyncMock, patch

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
            PAYOUT_ENABLED=True,
            PAYOUT_PROVIDER_TYPE="external_adapter",
            ALLOW_MOCK_PROVIDERS_IN_PRODUCTION=False,
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
