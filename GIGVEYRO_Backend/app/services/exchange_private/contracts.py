from typing import Protocol

from app.services.exchange_private.models import (
    ExchangeAccountInfo,
    ExchangeApiKeyInfo,
    ExchangeBalance,
)


class ExchangePrivateProvider(Protocol):
    """Read-only private exchange capability. It intentionally has no write methods."""

    async def get_api_key_info(self) -> ExchangeApiKeyInfo: ...

    async def get_account_info(self) -> ExchangeAccountInfo: ...

    async def get_balances(self) -> list[ExchangeBalance]: ...

    async def close(self) -> None: ...
