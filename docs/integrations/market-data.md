# Public market data integrations

GIGVEYRO Stage 1 integrates Binance and Bybit only as public, read-only market
observation providers. It does not configure API keys, sign requests, access an
account, trade, transfer, withdraw, or move money. `PAYOUT_ENABLED=false` remains
the mandatory safe state.

## Endpoints

- Binance uses `https://data-api.binance.vision/api/v3/ticker/price` with a
  whitelisted `symbol` query parameter. Binance documents the market-data-only
  host and classifies public market endpoints as security type `NONE`:
  <https://developers.binance.com/en/docs/products/spot/rest-api>.
- Bybit uses `https://api.bybit.com/v5/market/tickers` with `category=spot` and a
  whitelisted `symbol`. The official V5 response provides `lastPrice`, best bid,
  best ask, and the server timestamp:
  <https://bybit-exchange.github.io/docs/v5/market/tickers>.

No authentication headers are sent. Stage 1 supports only `BTCUSDT` and
`ETHUSDT` by default; arbitrary symbol proxying is rejected.

## Runtime design

Both providers return a normalized `MarketQuote` containing provider, symbol,
`Decimal` bid/ask/last values, upstream timestamp when available, receipt time,
and latency. A shared pooled async HTTP client is created and closed by the
FastAPI lifespan. Requests have bounded concurrency, separate HTTP timeouts,
bounded exponential-backoff retries, and rate-limit-aware `Retry-After` handling.
Permanent 4xx responses and invalid symbols are not retried.

The aggregator queries the configured primary provider and fails over to the
secondary. Repeated failures open a lightweight cooldown circuit; the next call
after cooldown is the half-open probe. When both quotes are available, their
deviation is measured in basis points and reported as degraded when it exceeds
`MARKET_MAX_DEVIATION_BPS`. This is diagnostics, not an arbitrage engine.

Successful quotes are cached briefly in Redis under
`gigveyro:<env>:market:<provider>:<symbol>`. Redis failure falls back to a direct
provider call. Expired cache entries are never returned as live data. Per-process
singleflight prevents concurrent cache misses from stampeding the primary.

## Diagnostics and observability

OWNER diagnostics show Binance, Bybit, primary/fallback role, connectivity,
latency, last successful quote time, cache mode, circuit state, and deviation.
Trading and payout status are explicitly disabled. `/health/diagnostics` includes
the same external state, but Binance and Bybit are intentionally excluded from
`/health/live` and `/health/ready` so an exchange outage does not take down the
core web service.

Metrics use only bounded provider/status labels:

- `gigveyro_market_provider_requests_total`
- `gigveyro_market_provider_latency_seconds`
- `gigveyro_market_provider_failovers_total`
- `gigveyro_market_provider_cache_hits_total`
- `gigveyro_market_provider_quote_age_seconds`

Logs contain structured event names and summary metadata, never full upstream
payloads or credentials.

## TJS limitation and Deal safety

Binance and Bybit public spot APIs do not provide a supported liquid `USDT/TJS`
market. A crypto `BTCUSDT` or `ETHUSDT` quote cannot mathematically produce TJS
per USDT. Consequently this Stage 1 integration does **not** replace or feed the
existing Deal exchange-rate path. A separate authoritative fiat-rate provider is
required before changing the GIGVEYRO TJS/USDT business rate.

Unofficial Binance/Bybit P2P endpoints, scraping, and the demo `10.90` rate must
not be presented as live exchange data.

## Future private-key policy

Any future private integration must start with a separate read-only key. Trading
and withdrawals must remain disabled, IP allowlisting should be enabled where
supported, production must use a dedicated key, and personal high-privilege keys
must never be reused. No private provider implementation is active in Stage 1.
