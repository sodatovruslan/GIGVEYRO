from decimal import Decimal

from cryptography.fernet import Fernet
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "GIGVEYRO"
    APP_ENV: str = "development"
    DEBUG: bool = False
    DOCS_ENABLED: bool = True
    DATABASE_URL: str

    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    SESSION_CLEANUP_RETENTION_DAYS: int = 30

    # Two-factor authentication (TOTP, owner-only for now)
    TOTP_ENCRYPTION_KEY: str
    OWNER_2FA_REQUIRED: bool = False
    TWO_FACTOR_SETUP_EXPIRE_MINUTES: int = 10
    TWO_FACTOR_CHALLENGE_EXPIRE_SECONDS: int = 300
    TWO_FACTOR_MAX_CHALLENGE_ATTEMPTS: int = 5
    TWO_FACTOR_RECOVERY_CODE_COUNT: int = 10
    TWO_FACTOR_VERIFY_RATE_LIMIT_REQUESTS: int = 10
    TWO_FACTOR_VERIFY_RATE_LIMIT_WINDOW_SECONDS: int = 300

    REALTIME_TICKET_EXPIRE_SECONDS: int = 30
    REALTIME_HEARTBEAT_SECONDS: float = 25.0
    REALTIME_OUTBOX_POLL_SECONDS: float = 0.25

    MAX_ACTIVE_REQUISITES_PER_USER: int = 10

    DEAL_TTL_MINUTES: int = 30
    DEMO_USDT_TJS_RATE: Decimal = Decimal("10.90")

    # Security & CORS Settings
    CORS_ALLOWED_ORIGINS: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    ALLOWED_HOSTS: list[str] = ["localhost", "127.0.0.1", "test"]

    # Rate Limiting Settings
    LOGIN_RATE_LIMIT_REQUESTS: int = 5
    LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = 60
    DEFAULT_RATE_LIMIT_REQUESTS: int = 100
    DEFAULT_RATE_LIMIT_WINDOW_SECONDS: int = 60

    # Provider Selector Settings
    DEPOSIT_PROVIDER_TYPE: str = "mock"  # "mock" or "trongrid"
    EXCHANGE_RATE_PROVIDER_TYPE: str = "fallback"  # "configured", "external", "fallback"
    PAYOUT_PROVIDER_TYPE: str = "mock"  # "mock" or "external_adapter"
    PAYOUT_ENABLED: bool = False  # Production safety switch - Disabled by default!

    # Exchange Rate External API Provider Settings
    EXCHANGE_RATE_API_URL: str = "https://api.binance.com/api/v3/ticker/price?symbol=USDTUAH"
    EXCHANGE_RATE_TIMEOUT_SECONDS: float = 5.0
    EXCHANGE_RATE_MAX_RETRIES: int = 3
    EXCHANGE_RATE_CACHE_TTL_SECONDS: int = 60

    # Public/read-only exchange market data (observation only; never used for Deal rates)
    BINANCE_PUBLIC_BASE_URL: str = "https://data-api.binance.vision"
    BYBIT_PUBLIC_BASE_URL: str = "https://api.bybit.com"
    MARKET_DATA_PRIMARY: str = "binance"
    MARKET_DATA_SECONDARY: str = "bybit"
    MARKET_DATA_SYMBOLS: list[str] = ["BTCUSDT", "ETHUSDT"]
    MARKET_DATA_CACHE_TTL_SECONDS: int = 10
    MARKET_DATA_TIMEOUT_SECONDS: float = 5.0
    MARKET_DATA_MAX_RETRIES: int = 2
    MARKET_DATA_MAX_CONCURRENCY: int = 4
    MARKET_MAX_DEVIATION_BPS: int = 100
    MARKET_CIRCUIT_FAILURE_THRESHOLD: int = 3
    MARKET_CIRCUIT_COOLDOWN_SECONDS: int = 30

    # USDT TRC20 & TRON Settings
    USDT_TRC20_CONTRACT_ADDRESS: str = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
    USDT_TRC20_DEPOSIT_ADDRESS: str = "TMOCK_GIGVEYRO_DEPOSIT_ADDRESS"
    DEPOSIT_TTL_MINUTES: int = 30
    TRC20_REQUIRED_CONFIRMATIONS: int = 20

    # TRON / TRC20 Real-shaped Read-Only Provider Settings
    TRONGRID_API_URL: str = "https://api.trongrid.io"
    TRONGRID_API_KEY: str = ""
    TRON_SCANNER_TIMEOUT_SECONDS: float = 10.0

    # Payout Provider Settings
    PAYOUT_API_URL: str = "https://api.payout-provider-mock.internal"
    PAYOUT_API_KEY: str = ""

    # ── Production Infrastructure Settings (AI #4 — Infra) ──────────────────

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_MAX_CONNECTIONS: int = 20

    # Background Workers (ARQ)
    WORKER_CONCURRENCY: int = 4
    OUTBOX_BATCH_SIZE: int = 50
    SCAN_INTERVAL_SECONDS: int = 60

    # Error Monitoring (optional — disabled when empty)
    SENTRY_DSN: str = ""
    SENTRY_TRACES_SAMPLE_RATE: float = 0.1

    # Production Provider Policy
    # Set to True in production to allow mock providers (e.g. for testing in staging)
    ALLOW_MOCK_PROVIDERS_IN_PRODUCTION: bool = False

    # Database Connection Pool (production tuning)
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800  # Recycle connections every 30 min

    # ── Realtime & Web Scaling Settings ─────────────────────────────────────
    REALTIME_BROKER: str = "inmemory"  # "inmemory" or "redis"
    WEB_CONCURRENCY: int = 1

    # Redis Namespace / Key Prefix (gigveyro:<env> by default)
    REDIS_KEY_PREFIX: str = ""

    # Rate Limiter Settings
    RATE_LIMIT_FAIL_MODE: str = "open"  # "open" or "closed"

    # Metrics Security Settings
    METRICS_ENABLED: bool = True
    METRICS_AUTH_TOKEN: str = ""

    @model_validator(mode="after")
    def validate_totp_encryption_key(self) -> "Settings":
        # A malformed key is a hard functional bug (every TOTP encrypt/decrypt
        # call would fail), not just a production-strength policy, so this is
        # checked in every environment, not only production.
        try:
            Fernet(self.TOTP_ENCRYPTION_KEY.encode("utf-8"))
        except Exception as exc:
            raise ValueError(
                "TOTP_ENCRYPTION_KEY must be a valid urlsafe-base64-encoded 32-byte Fernet key "
                '(generate with: python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())")'
            ) from exc
        return self

    @model_validator(mode="after")
    def default_redis_prefix(self) -> "Settings":
        if not self.REDIS_KEY_PREFIX:
            self.REDIS_KEY_PREFIX = f"gigveyro:{self.APP_ENV}"
        return self

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        if self.APP_ENV == "production":
            if self.DEBUG:
                raise ValueError("DEBUG must be False in production")
            if "CHANGE_ME" in self.JWT_SECRET_KEY or len(self.JWT_SECRET_KEY) < 32:
                raise ValueError("JWT_SECRET_KEY must be strong (>=32 chars) in production")
            if "CHANGE_ME" in self.TOTP_ENCRYPTION_KEY:
                raise ValueError("TOTP_ENCRYPTION_KEY must be a real generated key in production")
            if "*" in self.CORS_ALLOWED_ORIGINS:
                raise ValueError("Wildcard CORS origins are forbidden in production")
            # Production Redis requirement
            if "localhost" in self.REDIS_URL or "127.0.0.1" in self.REDIS_URL:
                import logging

                logging.getLogger(__name__).warning(
                    "REDIS_URL points to localhost in production — "
                    "ensure this is intentional (e.g. Docker internal network)."
                )

            # Realtime horizontal scaling check
            if self.REALTIME_BROKER == "inmemory" and self.WEB_CONCURRENCY > 1:
                raise ValueError(
                    "REALTIME_BROKER must be set to 'redis' in production "
                    "when WEB_CONCURRENCY > 1 (horizontal scaling)."
                )

            # Production mock provider policy
            if not self.ALLOW_MOCK_PROVIDERS_IN_PRODUCTION:
                if self.DEPOSIT_PROVIDER_TYPE == "mock":
                    raise ValueError(
                        "DEPOSIT_PROVIDER_TYPE=mock is forbidden in production. "
                        "Configure a real deposit provider or set "
                        "ALLOW_MOCK_PROVIDERS_IN_PRODUCTION=True."
                    )
                if self.PAYOUT_PROVIDER_TYPE == "mock" and self.PAYOUT_ENABLED:
                    raise ValueError(
                        "PAYOUT_ENABLED=True with PAYOUT_PROVIDER_TYPE=mock is "
                        "forbidden in production. Configure a real payout provider "
                        "or set ALLOW_MOCK_PROVIDERS_IN_PRODUCTION=True."
                    )
                if self.PAYOUT_ENABLED:
                    if not self.PAYOUT_API_KEY or "mock" in self.PAYOUT_API_URL:
                        raise ValueError(
                            "PAYOUT_ENABLED=True requires real payout provider settings "
                            "(PAYOUT_API_KEY and real PAYOUT_API_URL) in production"
                        )
            if self.DOCS_ENABLED:
                raise ValueError("DOCS_ENABLED must be False in production")
            if self.METRICS_ENABLED and len(self.METRICS_AUTH_TOKEN) < 32:
                raise ValueError(
                    "METRICS_AUTH_TOKEN must be strong (>=32 chars) when metrics are "
                    "enabled in production"
                )
        return self

    @model_validator(mode="after")
    def validate_market_data_settings(self) -> "Settings":
        providers = {"binance", "bybit"}
        if self.MARKET_DATA_PRIMARY not in providers:
            raise ValueError("MARKET_DATA_PRIMARY must be 'binance' or 'bybit'")
        if self.MARKET_DATA_SECONDARY not in providers:
            raise ValueError("MARKET_DATA_SECONDARY must be 'binance' or 'bybit'")
        if self.MARKET_DATA_PRIMARY == self.MARKET_DATA_SECONDARY:
            raise ValueError("MARKET_DATA_PRIMARY and MARKET_DATA_SECONDARY must differ")
        if not self.MARKET_DATA_SYMBOLS:
            raise ValueError("MARKET_DATA_SYMBOLS must not be empty")
        self.MARKET_DATA_SYMBOLS = [symbol.upper() for symbol in self.MARKET_DATA_SYMBOLS]
        return self


settings = Settings()
