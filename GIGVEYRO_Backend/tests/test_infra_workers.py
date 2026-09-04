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


def _production_settings(**overrides) -> Settings:
    values = {
        "DATABASE_URL": "postgresql+asyncpg://user:pass@db/test",
        "JWT_SECRET_KEY": "a-very-long-jwt-secret-key-minimum-32chars",
        "APP_ENV": "production",
        "DEBUG": False,
        "CORS_ALLOWED_ORIGINS": ["https://example.com"],
        "ALLOWED_HOSTS": ["example.com"],
        "DEPOSIT_PROVIDER_TYPE": "trongrid",
        "TRONGRID_API_KEY": "test-trongrid-read-only-key",
        "PAYOUT_ENABLED": False,
        "PAYOUT_PROVIDER_MODE": "disabled",
        "ALLOW_MOCK_PROVIDERS_IN_PRODUCTION": False,
        "DOCS_ENABLED": False,
        "METRICS_ENABLED": False,
        "REDIS_URL": "redis://redis:6379/0",
        "REALTIME_BROKER": "redis",
        "RATE_LIMIT_FAIL_MODE": "closed",
    }
    values.update(overrides)
    return Settings(**values)


class TestProductionConfigValidation:
    """Production settings validation rules."""

    def test_production_telegram_requires_webhook_and_real_secret(self):
        common = {
            "TELEGRAM_BOT_ENABLED": True,
            "TELEGRAM_BOT_TOKEN": "test-placeholder",
            "TELEGRAM_BOT_USERNAME": "test_bot",
            "TELEGRAM_DELIVERY_ENABLED": True,
        }
        with pytest.raises(ValueError, match="must use webhook mode"):
            _production_settings(**common, TELEGRAM_BOT_MODE="polling")
        with pytest.raises(ValueError, match="must be strong and valid"):
            _production_settings(
                **common,
                TELEGRAM_BOT_MODE="webhook",
                TELEGRAM_WEBHOOK_SECRET="CHANGE_ME_AT_LEAST_32_RANDOM_CHARACTERS",
                TELEGRAM_WEBHOOK_BASE_URL="https://example.com",
            )

    def test_payout_enabled_with_mock_provider_rejected_in_production(self):
        """Production must reject PAYOUT_ENABLED=True with mock payout provider."""
        with pytest.raises(ValueError, match="simulated payout mode"):
            _production_settings(
                DATABASE_URL="postgresql+asyncpg://user:pass@db/test",
                JWT_SECRET_KEY="a-very-long-jwt-secret-key-minimum-32chars",
                APP_ENV="production",
                DEBUG=False,
                CORS_ALLOWED_ORIGINS=["https://example.com"],
                DEPOSIT_PROVIDER_TYPE="trongrid",
                PAYOUT_ENABLED=True,
                PAYOUT_PROVIDER_MODE="simulated",
                PAYOUT_SIMULATION_ENABLED=True,
                ALLOW_MOCK_PROVIDERS_IN_PRODUCTION=False,
            )

    def test_live_payout_provider_is_rejected_in_every_environment(self):
        """This stage has no live provider implementation."""
        with pytest.raises(ValueError, match="no approved live provider"):
            Settings(PAYOUT_PROVIDER_MODE="live")

    def test_payout_enabled_false_is_always_safe(self):
        """PAYOUT_ENABLED=False is always safe regardless of provider."""
        s = _production_settings(
            DATABASE_URL="postgresql+asyncpg://user:pass@db/test",
            JWT_SECRET_KEY="a-very-long-jwt-secret-key-minimum-32chars",
            APP_ENV="production",
            DEBUG=False,
            CORS_ALLOWED_ORIGINS=["https://example.com"],
            DEPOSIT_PROVIDER_TYPE="trongrid",
            PAYOUT_ENABLED=False,
            PAYOUT_PROVIDER_MODE="disabled",
            ALLOW_MOCK_PROVIDERS_IN_PRODUCTION=False,
            DOCS_ENABLED=False,
            METRICS_ENABLED=False,
        )
        assert s.PAYOUT_ENABLED is False

    def test_production_rejects_enabled_api_docs(self):
        with pytest.raises(ValueError, match="DOCS_ENABLED must be False in production"):
            _production_settings(
                DATABASE_URL="postgresql+asyncpg://user:pass@db/test",
                JWT_SECRET_KEY="a-very-long-jwt-secret-key-minimum-32chars",
                APP_ENV="production",
                DEBUG=False,
                CORS_ALLOWED_ORIGINS=["https://example.com"],
                DEPOSIT_PROVIDER_TYPE="trongrid",
                PAYOUT_ENABLED=False,
                DOCS_ENABLED=True,
                METRICS_ENABLED=False,
            )

    def test_production_rejects_unprotected_metrics(self):
        with pytest.raises(ValueError, match="METRICS_AUTH_TOKEN must be strong"):
            _production_settings(
                DATABASE_URL="postgresql+asyncpg://user:pass@db/test",
                JWT_SECRET_KEY="a-very-long-jwt-secret-key-minimum-32chars",
                APP_ENV="production",
                DEBUG=False,
                CORS_ALLOWED_ORIGINS=["https://example.com"],
                DEPOSIT_PROVIDER_TYPE="trongrid",
                PAYOUT_ENABLED=False,
                DOCS_ENABLED=False,
                METRICS_ENABLED=True,
                METRICS_AUTH_TOKEN="",
            )

    def test_debug_true_rejected_in_production(self):
        """DEBUG=True is rejected in production."""
        with pytest.raises(ValueError, match="DEBUG must be False"):
            _production_settings(
                DATABASE_URL="postgresql+asyncpg://user:pass@db/test",
                JWT_SECRET_KEY="a-very-long-jwt-secret-key-minimum-32chars",
                APP_ENV="production",
                DEBUG=True,
            )

    def test_weak_jwt_key_rejected_in_production(self):
        """Short/default JWT key is rejected in production."""
        with pytest.raises(ValueError, match="JWT_SECRET_KEY must be strong"):
            _production_settings(
                DATABASE_URL="postgresql+asyncpg://user:pass@db/test",
                JWT_SECRET_KEY="CHANGE_ME",
                APP_ENV="production",
                DEBUG=False,
            )

    def test_wildcard_cors_rejected_in_production(self):
        """Wildcard CORS origin is rejected in production."""
        with pytest.raises(ValueError, match="Wildcard CORS origins"):
            _production_settings(
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
            _production_settings(
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
            _production_settings(
                DATABASE_URL="postgresql+asyncpg://user:pass@db/test",
                JWT_SECRET_KEY="a-very-long-jwt-secret-key-minimum-32chars",
                APP_ENV="production",
                DEBUG=False,
                DEPOSIT_PROVIDER_TYPE="trongrid",
                REALTIME_BROKER="inmemory",
                WEB_CONCURRENCY=2,
            )

    def test_production_rejects_live_mode_even_with_credentials(self):
        with pytest.raises(ValueError, match="no approved live provider"):
            _production_settings(
                DATABASE_URL="postgresql+asyncpg://user:pass@db/test",
                JWT_SECRET_KEY="a-very-long-jwt-secret-key-minimum-32chars",
                APP_ENV="production",
                DEBUG=False,
                DEPOSIT_PROVIDER_TYPE="trongrid",
                PAYOUT_PROVIDER_MODE="live",
                ALLOW_MOCK_PROVIDERS_IN_PRODUCTION=False,
                DOCS_ENABLED=False,
                METRICS_ENABLED=False,
            )

    def test_environment_modes_and_debug_contract(self):
        with pytest.raises(ValueError, match="APP_ENV must be one of"):
            Settings(APP_ENV="release")
        with pytest.raises(ValueError, match="DEBUG must be False in staging"):
            Settings(APP_ENV="staging", DEBUG=True)
        assert Settings(APP_ENV="development", DEBUG=True).DEBUG is True

    @pytest.mark.parametrize(
        ("overrides", "message"),
        [
            ({"CORS_ALLOWED_ORIGINS": ["http://example.com"]}, "explicit HTTPS"),
            ({"ALLOWED_HOSTS": ["localhost"]}, "explicit public hosts"),
            ({"REDIS_URL": "redis://localhost:6379/0"}, "must not use localhost"),
            ({"REALTIME_BROKER": "inmemory"}, "must be 'redis'"),
            ({"RATE_LIMIT_FAIL_MODE": "open"}, "must not be 'open'"),
        ],
    )
    def test_production_dependency_boundaries_fail_closed(self, overrides, message):
        with pytest.raises(ValueError, match=message):
            _production_settings(**overrides)


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
        provider.last_scan_upper_timestamp_ms = 1_700_000_123_456
        provider.aclose = AsyncMock()
        watermark_store = MagicMock()
        watermark_store.get = AsyncMock(return_value=None)
        watermark_store.set = AsyncMock()
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
            result = await _run_scan(
                "scanner-test", 1, watermark_store=watermark_store
            )

        assert result == {"status": "ok", "processed": 2}
        session.commit.assert_awaited_once()
        watermark_store.set.assert_awaited_once()
        provider.aclose.assert_awaited_once()

    async def test_deposit_scanner_uses_redis_watermark_with_overlap(self):
        from app.workers.jobs.deposit_scanner import _scan_lower_bound

        watermark_store = MagicMock()
        watermark_store.get = AsyncMock(return_value=b"1700000000000")
        with patch("app.workers.jobs.deposit_scanner.settings") as scanner_settings:
            scanner_settings.TRONGRID_SCAN_OVERLAP_SECONDS = 300
            lower_bound = await _scan_lower_bound(watermark_store)

        assert lower_bound == 1_699_999_700_000

    async def test_deposit_scanner_missing_watermark_replays_active_intent_window(self):
        from app.workers.jobs.deposit_scanner import _scan_lower_bound

        watermark_store = MagicMock()
        watermark_store.get = AsyncMock(return_value=None)
        with (
            patch("app.workers.jobs.deposit_scanner.settings") as scanner_settings,
            patch(
                "app.workers.jobs.deposit_scanner.time.time_ns",
                return_value=2_000_000_000_000_000,
            ),
        ):
            scanner_settings.TRONGRID_SCAN_OVERLAP_SECONDS = 300
            scanner_settings.DEPOSIT_TTL_MINUTES = 30
            lower_bound = await _scan_lower_bound(watermark_store)

        assert lower_bound == 1_997_900_000


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

    def test_worker_entrypoint_uses_supported_arq_cli(self):
        import worker_entrypoint

        with patch("arq.cli.cli") as cli:
            worker_entrypoint.main()

        cli.assert_called_once_with()

    async def test_worker_shutdown_cancels_heartbeat_cleanly(self):
        """Worker shutdown treats heartbeat cancellation as normal lifecycle."""
        from app.workers.arq_settings import shutdown

        heartbeat = asyncio.create_task(asyncio.sleep(60))
        with patch("app.infra.redis_client.close_redis") as close_redis:
            await shutdown({"heartbeat_task": heartbeat})

        assert heartbeat.cancelled()
        close_redis.assert_awaited_once()
