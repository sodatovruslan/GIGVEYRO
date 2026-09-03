from decimal import Decimal

from cryptography.fernet import Fernet
from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "GIGVEYRO"
    APP_ENV: str = "development"
    # Development is verbose by default. Staging/production must explicitly set false.
    DEBUG: bool = True
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

    # Telegram is an optional, read-only communication channel. It never authorizes finance.
    TELEGRAM_BOT_ENABLED: bool = False
    TELEGRAM_BOT_TOKEN: SecretStr = SecretStr("")
    TELEGRAM_BOT_USERNAME: str = ""
    TELEGRAM_DELIVERY_ENABLED: bool = False
    TELEGRAM_BOT_MODE: str = "polling"  # polling (development) or webhook (production)
    TELEGRAM_WEBHOOK_SECRET: SecretStr = SecretStr("")
    TELEGRAM_WEBHOOK_BASE_URL: str = ""
    TELEGRAM_WEB_APP_URL: str = "http://localhost:3000"
    TELEGRAM_LINK_TOKEN_TTL_MINUTES: int = 10
    TELEGRAM_API_TIMEOUT_SECONDS: float = 8.0
    TELEGRAM_DELIVERY_MAX_ATTEMPTS: int = 5
    TELEGRAM_COMMAND_RATE_LIMIT_REQUESTS: int = 20
    TELEGRAM_COMMAND_RATE_LIMIT_WINDOW_SECONDS: int = 60

    # Provider Selector Settings
    DEPOSIT_PROVIDER_TYPE: str = "mock"  # "mock" or "trongrid"
    EXCHANGE_RATE_PROVIDER_TYPE: str = "fallback"  # "configured", "fallback", "business"
    PAYOUT_PROVIDER_TYPE: str = "mock"  # "mock" or "external_adapter"
    PAYOUT_ENABLED: bool = False  # Production safety switch - Disabled by default!
    PAYOUT_PROVIDER_MODE: str = "disabled"  # controlled plane: disabled|simulated; live rejected
    PAYOUT_SIMULATION_ENABLED: bool = False

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
    MARKET_DATA_SYMBOLS: list[str] = ["BTCUSDT", "ETHUSDT", "USDCUSDT"]
    MARKET_DATA_CACHE_TTL_SECONDS: int = 10
    MARKET_DATA_TIMEOUT_SECONDS: float = 5.0
    MARKET_DATA_MAX_RETRIES: int = 2
    MARKET_DATA_MAX_CONCURRENCY: int = 4
    MARKET_MAX_DEVIATION_BPS: int = 100
    MARKET_CIRCUIT_FAILURE_THRESHOLD: int = 3
    MARKET_CIRCUIT_COOLDOWN_SECONDS: int = 30

    # Private exchange observation (backend-only; no write capabilities)
    BYBIT_PRIVATE_ENABLED: bool = False
    BYBIT_API_KEY: SecretStr = SecretStr("")
    BYBIT_API_SECRET: SecretStr = SecretStr("")
    BYBIT_RECV_WINDOW_MS: int = 5000
    BYBIT_PRIVATE_TIMEOUT_SECONDS: float = 8.0
    BYBIT_PRIVATE_MAX_RETRIES: int = 2

    # Future payout-write credentials are intentionally isolated from treasury credentials.
    # This stage contains no network-capable write provider and all values default fail-closed.
    BYBIT_WRITE_ENABLED: bool = False
    BYBIT_WRITE_API_KEY: SecretStr = SecretStr("")
    BYBIT_WRITE_API_SECRET: SecretStr = SecretStr("")
    BYBIT_WRITE_PERMISSION_VERIFIED: bool = False
    BYBIT_WRITE_IP_WHITELIST_VERIFIED: bool = False
    BYBIT_LIVE_RECONCILIATION_VERIFIED: bool = False
    BYBIT_WITHDRAW_METADATA_MAX_AGE_SECONDS: int = 60

    # Authoritative fiat-rate composition (official USD/TJS + explicit USDT peg policy)
    NBT_FIAT_BASE_URL: str = "https://nbt.tj/en/kurs/export_xml.php"
    EXCHANGE_RATE_API_BASE_URL: str = "https://open.er-api.com/v6/latest/USD"
    FIAT_RATE_PRIMARY: str = "nbt"
    FIAT_RATE_SECONDARY: str = "exchange_rate_api"
    FIAT_ALLOW_INDICATIVE_FALLBACK: bool = False
    FIAT_RATE_CACHE_TTL_SECONDS: int = 21600
    FIAT_RATE_MAX_AGE_SECONDS: int = 345600
    FIAT_RATE_MAX_DEVIATION_BPS: int = 500
    FIAT_RATE_TIMEOUT_SECONDS: float = 8.0
    FIAT_RATE_MAX_RETRIES: int = 1
    FIAT_RATE_MAX_CONCURRENCY: int = 2
    FIAT_RATE_MIN_TJS_PER_USD: Decimal = Decimal("5")
    FIAT_RATE_MAX_TJS_PER_USD: Decimal = Decimal("20")
    USDT_PEG_MODE: str = "fixed"
    USDT_FIXED_USD_RATE: Decimal = Decimal("1.0")
    BUSINESS_RATE_MARKUP_BPS: int = 0
    BUSINESS_RATE_SPREAD_BPS: int = 0
    BUSINESS_RATE_POLICY_VERSION: str = "official-fiat-fixed-peg-v1"
    BUSINESS_RATE_MIN_TJS_PER_USDT: Decimal = Decimal("5")
    BUSINESS_RATE_MAX_TJS_PER_USDT: Decimal = Decimal("20")
    FIAT_CONVERSION_CACHE_TTL_SECONDS: int = 21600
    FIAT_CONVERSION_MAX_AGE_SECONDS: int = 345600
    FIAT_CONVERSION_MIN_TJS_PER_RUB: Decimal = Decimal("0.01")
    FIAT_CONVERSION_MAX_TJS_PER_RUB: Decimal = Decimal("1")
    FIAT_CONVERSION_MARKUP_BPS: int = 0
    FIAT_CONVERSION_FEE_BPS: int = 0
    FIAT_CONVERSION_POLICY_VERSION: str = "nbt-official-zero-adjustment-v1"

    # USDT TRC20 & TRON Settings
    USDT_TRC20_CONTRACT_ADDRESS: str = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
    USDT_TRC20_DECIMALS: int = 6
    USDT_TRC20_DEPOSIT_ADDRESS: str = "TMOCK_GIGVEYRO_DEPOSIT_ADDRESS"
    DEPOSIT_TTL_MINUTES: int = 30
    TRC20_REQUIRED_CONFIRMATIONS: int = 20

    # TRON / TRC20 Real-shaped Read-Only Provider Settings
    TRONGRID_API_URL: str = "https://api.trongrid.io"
    TRONGRID_API_KEY: SecretStr = SecretStr("")
    TRON_SCANNER_TIMEOUT_SECONDS: float = 10.0
    TRONGRID_MAX_RETRIES: int = 2
    TRONGRID_PAGE_SIZE: int = 100
    TRONGRID_MAX_PAGES: int = 10
    TRONGRID_SCAN_OVERLAP_SECONDS: int = 300

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
    def validate_environment_mode(self) -> "Settings":
        allowed = {"development", "test", "staging", "production"}
        if self.APP_ENV not in allowed:
            raise ValueError(f"APP_ENV must be one of: {', '.join(sorted(allowed))}")
        if self.APP_ENV in {"staging", "production"} and self.DEBUG:
            raise ValueError(f"DEBUG must be False in {self.APP_ENV}")
        return self

    @model_validator(mode="after")
    def validate_telegram_settings(self) -> "Settings":
        if self.TELEGRAM_BOT_MODE not in {"polling", "webhook"}:
            raise ValueError("TELEGRAM_BOT_MODE must be 'polling' or 'webhook'")
        if not 5 <= self.TELEGRAM_LINK_TOKEN_TTL_MINUTES <= 10:
            raise ValueError("TELEGRAM_LINK_TOKEN_TTL_MINUTES must be between 5 and 10")
        token = self.TELEGRAM_BOT_TOKEN.get_secret_value()
        if self.TELEGRAM_DELIVERY_ENABLED and not self.TELEGRAM_BOT_ENABLED:
            raise ValueError("TELEGRAM_DELIVERY_ENABLED requires TELEGRAM_BOT_ENABLED")
        if self.TELEGRAM_BOT_ENABLED and (not token or not self.TELEGRAM_BOT_USERNAME):
            raise ValueError("Enabled Telegram bot requires token and username")
        if self.APP_ENV == "production" and self.TELEGRAM_BOT_ENABLED:
            if self.TELEGRAM_BOT_MODE != "webhook":
                raise ValueError("Production Telegram bot must use webhook mode")
            secret = self.TELEGRAM_WEBHOOK_SECRET.get_secret_value()
            if "CHANGE_ME" in secret or len(secret) < 32 or any(
                char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
                for char in secret
            ):
                raise ValueError("Production Telegram webhook secret must be strong and valid")
            if not self.TELEGRAM_WEBHOOK_BASE_URL.startswith("https://"):
                raise ValueError("Production Telegram webhook base URL must use HTTPS")
        return self

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        if self.APP_ENV == "production":
            if "CHANGE_ME" in self.JWT_SECRET_KEY or len(self.JWT_SECRET_KEY) < 32:
                raise ValueError("JWT_SECRET_KEY must be strong (>=32 chars) in production")
            if "CHANGE_ME" in self.TOTP_ENCRYPTION_KEY:
                raise ValueError("TOTP_ENCRYPTION_KEY must be a real generated key in production")
            if "*" in self.CORS_ALLOWED_ORIGINS:
                raise ValueError("Wildcard CORS origins are forbidden in production")
            if not self.CORS_ALLOWED_ORIGINS or any(
                not origin.startswith("https://") for origin in self.CORS_ALLOWED_ORIGINS
            ):
                raise ValueError("Production CORS origins must be explicit HTTPS origins")
            if not self.ALLOWED_HOSTS or any(
                host in {"*", "localhost", "127.0.0.1"} for host in self.ALLOWED_HOSTS
            ):
                raise ValueError("Production ALLOWED_HOSTS must contain only explicit public hosts")
            # Realtime horizontal scaling check
            if self.REALTIME_BROKER == "inmemory" and self.WEB_CONCURRENCY > 1:
                raise ValueError(
                    "REALTIME_BROKER must be set to 'redis' in production "
                    "when WEB_CONCURRENCY > 1 (horizontal scaling)."
                )

            # Production provider policy
            if not self.ALLOW_MOCK_PROVIDERS_IN_PRODUCTION:
                if self.DEPOSIT_PROVIDER_TYPE == "mock":
                    raise ValueError(
                        "DEPOSIT_PROVIDER_TYPE=mock is forbidden in production. "
                        "Configure a real deposit provider or set "
                        "ALLOW_MOCK_PROVIDERS_IN_PRODUCTION=True."
                    )
                if self.PAYOUT_PROVIDER_MODE == "simulated" and self.PAYOUT_ENABLED:
                    raise ValueError(
                        "PAYOUT_ENABLED=True with simulated payout mode requires "
                        "ALLOW_MOCK_PROVIDERS_IN_PRODUCTION=True"
                    )
            if self.DOCS_ENABLED:
                raise ValueError("DOCS_ENABLED must be False in production")
            if self.METRICS_ENABLED and len(self.METRICS_AUTH_TOKEN) < 32:
                raise ValueError(
                    "METRICS_AUTH_TOKEN must be strong (>=32 chars) when metrics are "
                    "enabled in production"
                )
            if "localhost" in self.REDIS_URL or "127.0.0.1" in self.REDIS_URL:
                raise ValueError("Production REDIS_URL must not use localhost")
            if self.REALTIME_BROKER != "redis":
                raise ValueError("REALTIME_BROKER must be 'redis' in production")
            if self.RATE_LIMIT_FAIL_MODE == "open":
                raise ValueError("RATE_LIMIT_FAIL_MODE must not be 'open' in production")
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

    @model_validator(mode="after")
    def validate_trongrid_settings(self) -> "Settings":
        if self.DEPOSIT_PROVIDER_TYPE not in {"mock", "trongrid"}:
            raise ValueError("DEPOSIT_PROVIDER_TYPE must be 'mock' or 'trongrid'")
        if self.DEPOSIT_PROVIDER_TYPE == "trongrid":
            if not self.TRONGRID_API_URL.startswith("https://"):
                raise ValueError("TRONGRID_API_URL must use HTTPS")
            if self.APP_ENV == "production" and not self.TRONGRID_API_KEY.get_secret_value():
                raise ValueError("TRONGRID_API_KEY is required in production")
        if not 1 <= self.TRONGRID_PAGE_SIZE <= 200:
            raise ValueError("TRONGRID_PAGE_SIZE must be between 1 and 200")
        if not 1 <= self.TRONGRID_MAX_PAGES <= 100:
            raise ValueError("TRONGRID_MAX_PAGES must be between 1 and 100")
        if not 0 <= self.TRONGRID_MAX_RETRIES <= 5:
            raise ValueError("TRONGRID_MAX_RETRIES must be between 0 and 5")
        if not 0 <= self.TRONGRID_SCAN_OVERLAP_SECONDS <= 3600:
            raise ValueError("TRONGRID_SCAN_OVERLAP_SECONDS must be between 0 and 3600")
        if self.USDT_TRC20_DECIMALS != 6:
            raise ValueError("USDT_TRC20_DECIMALS must remain 6")
        return self

    @model_validator(mode="after")
    def validate_controlled_payout_settings(self) -> "Settings":
        if self.PAYOUT_PROVIDER_MODE not in {"disabled", "simulated", "live"}:
            raise ValueError("PAYOUT_PROVIDER_MODE must be disabled or simulated")
        if self.PAYOUT_PROVIDER_MODE == "live":
            raise ValueError(
                "PAYOUT_PROVIDER_MODE=live is unavailable: no approved live provider exists"
            )
        if self.BYBIT_WRITE_ENABLED:
            raise ValueError(
                "BYBIT_WRITE_ENABLED=true is unavailable: write network transport is disabled"
            )
        if not 10 <= self.BYBIT_WITHDRAW_METADATA_MAX_AGE_SECONDS <= 300:
            raise ValueError("BYBIT_WITHDRAW_METADATA_MAX_AGE_SECONDS must be between 10 and 300")
        if self.PAYOUT_PROVIDER_MODE == "simulated" and not self.PAYOUT_SIMULATION_ENABLED:
            # Safe configuration is allowed to start, but execution remains blocked.
            return self
        return self

    @model_validator(mode="after")
    def validate_fiat_rate_settings(self) -> "Settings":
        providers = {"nbt", "exchange_rate_api"}
        if self.FIAT_RATE_PRIMARY not in providers:
            raise ValueError("FIAT_RATE_PRIMARY must be 'nbt' or 'exchange_rate_api'")
        if self.FIAT_RATE_SECONDARY not in providers:
            raise ValueError("FIAT_RATE_SECONDARY must be 'nbt' or 'exchange_rate_api'")
        if self.FIAT_RATE_PRIMARY == self.FIAT_RATE_SECONDARY:
            raise ValueError("FIAT_RATE_PRIMARY and FIAT_RATE_SECONDARY must differ")
        if self.USDT_PEG_MODE not in {"fixed", "market"}:
            raise ValueError("USDT_PEG_MODE must be 'fixed' or 'market'")
        if self.FIAT_RATE_MIN_TJS_PER_USD >= self.FIAT_RATE_MAX_TJS_PER_USD:
            raise ValueError("FIAT rate sanity minimum must be below maximum")
        if not Decimal("0.5") <= self.USDT_FIXED_USD_RATE <= Decimal("1.5"):
            raise ValueError("USDT_FIXED_USD_RATE is outside the broad safety range")
        if self.BUSINESS_RATE_MIN_TJS_PER_USDT >= self.BUSINESS_RATE_MAX_TJS_PER_USDT:
            raise ValueError("Business rate sanity minimum must be below maximum")
        if self.FIAT_CONVERSION_MIN_TJS_PER_RUB >= self.FIAT_CONVERSION_MAX_TJS_PER_RUB:
            raise ValueError("TJS/RUB sanity minimum must be below maximum")
        if self.FIAT_CONVERSION_MARKUP_BPS != 0 or self.FIAT_CONVERSION_FEE_BPS != 0:
            raise ValueError("TJS/RUB markup and fee must remain zero until explicitly approved")
        if self.BYBIT_PRIVATE_ENABLED and (
            not self.BYBIT_API_KEY.get_secret_value()
            or not self.BYBIT_API_SECRET.get_secret_value()
        ):
            raise ValueError("Bybit private API credentials are required when enabled")
        if not 1000 <= self.BYBIT_RECV_WINDOW_MS <= 10000:
            raise ValueError("BYBIT_RECV_WINDOW_MS must be between 1000 and 10000")
        if not 0 <= self.BYBIT_PRIVATE_MAX_RETRIES <= 3:
            raise ValueError("BYBIT_PRIVATE_MAX_RETRIES must be between 0 and 3")
        return self


settings = Settings()
