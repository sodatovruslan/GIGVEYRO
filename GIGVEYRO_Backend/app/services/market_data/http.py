from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

import httpx

from app.services.market_data.errors import (
    ProviderBadResponse,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
    ProviderUnsupportedSymbol,
)

logger = logging.getLogger(__name__)


class MarketHttpClient:
    """Shared pooled async client with bounded retries and concurrency."""

    def __init__(
        self,
        *,
        timeout_seconds: float,
        max_retries: int,
        max_concurrency: int,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        timeout = httpx.Timeout(
            timeout_seconds,
            connect=min(timeout_seconds, 3.0),
            read=timeout_seconds,
            write=timeout_seconds,
            pool=timeout_seconds,
        )
        self._client = client or httpx.AsyncClient(
            timeout=timeout,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            headers={"User-Agent": "GIGVEYRO-MarketData/1.0"},
        )
        self._owns_client = client is None
        self._max_retries = max_retries
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def get_json(
        self,
        *,
        provider: str,
        url: str,
        params: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        response = await self._get_response(provider=provider, url=url, params=params)
        try:
            payload = json.loads(response.text, parse_float=Decimal)
        except ValueError as exc:
            raise ProviderBadResponse(f"{provider} returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ProviderBadResponse(f"{provider} returned a non-object response")
        return payload

    async def get_text(
        self,
        *,
        provider: str,
        url: str,
        params: Mapping[str, str] | None = None,
    ) -> str:
        response = await self._get_response(provider=provider, url=url, params=params)
        return response.text

    async def _get_response(
        self,
        *,
        provider: str,
        url: str,
        params: Mapping[str, str] | None,
    ) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 2):
            try:
                async with self._semaphore:
                    response = await self._client.get(url, params=params)
                if response.status_code in (418, 429):
                    error = ProviderRateLimited(f"{provider} rate limited the request")
                    if attempt <= self._max_retries:
                        await asyncio.sleep(_retry_delay(response, attempt))
                        last_error = error
                        continue
                    raise error
                if response.status_code >= 500:
                    error = ProviderUnavailable(f"{provider} returned HTTP {response.status_code}")
                    if attempt <= self._max_retries:
                        await asyncio.sleep(_backoff(attempt))
                        last_error = error
                        continue
                    raise error
                if response.status_code >= 400:
                    raise ProviderUnsupportedSymbol(
                        f"{provider} rejected the requested symbol (HTTP {response.status_code})"
                    )
                return response
            except httpx.TimeoutException as exc:
                last_error = ProviderTimeout(f"{provider} request timed out")
                if attempt <= self._max_retries:
                    await asyncio.sleep(_backoff(attempt))
                    continue
                raise last_error from exc
            except httpx.RequestError as exc:
                last_error = ProviderUnavailable(f"{provider} connection failed")
                if attempt <= self._max_retries:
                    await asyncio.sleep(_backoff(attempt))
                    continue
                raise last_error from exc
        raise ProviderUnavailable(f"{provider} request failed") from last_error

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _backoff(attempt: int) -> float:
    return min(0.25 * (2 ** (attempt - 1)) + random.uniform(0, 0.1), 2.0)


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    value = response.headers.get("Retry-After")
    if value:
        try:
            return min(max(float(value), 0.0), 5.0)
        except ValueError:
            pass
    return _backoff(attempt)
