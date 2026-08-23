from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from app.infra.metrics import record_business_rate
from app.services.exchange_rate import ExchangeRateError, ExchangeRateProvider, ExchangeRateSnapshot
from app.services.fiat_rate.aggregator import FiatRateAggregator
from app.services.fiat_rate.errors import FiatProviderError
from app.services.fiat_rate.models import BusinessRateSnapshot, FiatSourceType
from app.services.market_data.aggregator import MarketDataAggregator
from app.services.market_data.errors import ProviderError

logger = logging.getLogger(__name__)
_RATE_QUANTUM = Decimal("0.00000001")


class BusinessExchangeRateService(ExchangeRateProvider):
    def __init__(
        self,
        *,
        fiat: FiatRateAggregator,
        market: MarketDataAggregator,
        peg_mode: str,
        fixed_usdt_usd_rate: Decimal,
        markup_bps: int,
        spread_bps: int,
        minimum_rate: Decimal,
        maximum_rate: Decimal,
        policy_version: str,
    ) -> None:
        self._fiat = fiat
        self._market = market
        self._peg_mode = peg_mode
        self._fixed_usdt_usd_rate = fixed_usdt_usd_rate
        self._adjustment_bps = Decimal(markup_bps + spread_bps)
        self._minimum_rate = minimum_rate
        self._maximum_rate = maximum_rate
        self._policy_version = policy_version

    async def calculate(self) -> BusinessRateSnapshot:
        try:
            fiat_quote = await self._fiat.get_rate("USD", "TJS")
        except FiatProviderError as exc:
            raise ExchangeRateError("Authoritative fiat rate is unavailable") from exc
        market_received_at = None
        if self._peg_mode == "fixed":
            usdt_usd_rate = self._fixed_usdt_usd_rate
            market_provider = "fixed_policy"
        elif self._peg_mode == "market":
            try:
                market_quote = await self._market.get_quote("USDCUSDT")
            except ProviderError as exc:
                raise ExchangeRateError("USDT market reference is unavailable") from exc
            usdt_usd_rate = Decimal(1) / market_quote.last
            market_provider = market_quote.provider
            market_received_at = market_quote.received_at
        else:
            raise ExchangeRateError("Unsupported USDT peg policy")

        adjustment = (Decimal(10_000) + self._adjustment_bps) / Decimal(10_000)
        rate = (fiat_quote.rate * usdt_usd_rate * adjustment).quantize(
            _RATE_QUANTUM, rounding=ROUND_HALF_UP
        )
        if not self._minimum_rate <= rate <= self._maximum_rate:
            raise ExchangeRateError("Composed business rate failed configured sanity bounds")
        degraded = fiat_quote.is_stale or fiat_quote.source_type != FiatSourceType.OFFICIAL
        mode = "fallback" if degraded else "live"
        snapshot = BusinessRateSnapshot(
            rate_tjs_per_usdt=rate,
            fiat_rate_tjs_per_usd=fiat_quote.rate,
            usdt_usd_rate=usdt_usd_rate,
            fiat_provider=fiat_quote.provider,
            fiat_source_type=fiat_quote.source_type,
            market_provider=market_provider,
            fiat_published_at=fiat_quote.published_at,
            market_received_at=market_received_at,
            calculated_at=datetime.now(UTC),
            peg_mode=self._peg_mode,
            policy_version=self._policy_version,
            mode=mode,
            is_degraded=degraded,
        )
        record_business_rate(mode)
        logger.info(
            "exchange.business_rate.calculated provider=%s pair=TJS/USDT mode=%s policy=%s",
            snapshot.fiat_provider,
            snapshot.mode,
            snapshot.policy_version,
        )
        return snapshot

    async def get_usdt_tjs_rate(self) -> Decimal:
        return (await self.calculate()).rate_tjs_per_usdt

    async def get_rate_snapshot(self) -> ExchangeRateSnapshot:
        snapshot = await self.calculate()
        return ExchangeRateSnapshot(
            rate=snapshot.rate_tjs_per_usdt,
            source=snapshot.fiat_provider,
            published_at=snapshot.fiat_published_at,
            calculated_at=snapshot.calculated_at,
            policy_version=snapshot.policy_version,
            mode=snapshot.mode,
            degraded=snapshot.is_degraded,
        )
