from decimal import Decimal

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
    DATABASE_URL: str

    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    MAX_ACTIVE_REQUISITES_PER_USER: int = 10

    DEAL_TTL_MINUTES: int = 30
    DEMO_USDT_TJS_RATE: Decimal = Decimal("10.90")

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


settings = Settings()
