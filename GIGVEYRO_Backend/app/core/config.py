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
    # Demo/dev-only fixed rate - NOT a production exchange rate source.
    # A later stage will replace ConfiguredExchangeRateProvider with a live
    # provider without DealService needing to change.
    DEMO_USDT_TJS_RATE: Decimal = Decimal("10.90")


settings = Settings()
