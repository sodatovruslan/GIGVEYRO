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


settings = Settings()
