# TJS fiat and GIGVEYRO business-rate policy

## Sources and semantics

The primary source is the National Bank of Tajikistan (NBT) public XML export:
`https://nbt.tj/en/kurs/export_xml.php`. GIGVEYRO requests an explicit ISO date and
looks back up to seven calendar days to find the most recent published USD/TJS rate.
The feed is public HTTPS, requires no API key, and is free to access. NBT describes
these as official rates; they are not a commitment by a bank to buy or sell currency
and must not be presented as a commercial, cash, or P2P rate.

NBT also documents a JSON endpoint at
`https://www.nbt.tj/en/kurs/document_gold_api.php`, but its documented live URL
returned HTTP 404 during the 2026-08-23 verification. The working, documented XML
export is therefore used instead of silently scraping HTML.

The secondary comparison source is ExchangeRate-API's public open endpoint:
`https://open.er-api.com/v6/latest/USD`. Its documentation confirms TJS support and
daily updates. It requires no key and is free with rate limiting. Its terms classify
the data as indicative and not recommended for transactions. Consequently,
`FIAT_ALLOW_INDICATIVE_FALLBACK=false` by default: it may provide diagnostics and
deviation monitoring, but a Deal-sensitive operation fails closed if NBT has no
acceptable quote. Attribution: [ExchangeRate-API](https://www.exchangerate-api.com/).

Documentation:

- NBT: https://www.nbt.tj/en/kurs/document_gold_api.php
- ExchangeRate-API open endpoint: https://www.exchangerate-api.com/docs/free
- Supported currencies: https://www.exchangerate-api.com/docs/supported-currencies
- ExchangeRate-API terms: https://www.exchangerate-api.com/terms

## Three distinct rates

- `OFFICIAL_FIAT_RATE`: NBT USD/TJS quote.
- `MARKET_REFERENCE_RATE`: public Binance/Bybit crypto or stablecoin quote.
- `BUSINESS_RATE`: deterministic GIGVEYRO TJS/USDT composition.

The default policy is explicit and has no hidden commercial adjustment:

```text
TJS_PER_USDT = TJS_PER_USD × USD_PER_USDT × (1 + adjustment_bps / 10000)
             = NBT_USD_TJS × 1.00000000 × 1.00000000
```

`USDT_PEG_MODE=fixed` means the configured assumption `1 USDT = 1 USD` is used.
`USDT_PEG_MODE=market` instead derives USDT/USD from the public `USDCUSDT` market
reference. BTCUSDT is never used to calculate TJS/USDT. Markup and spread both
default to zero and must not be changed without an approved business policy.

## Freshness, cache, and failure policy

Quotes are normalized as `FiatQuote` with `Decimal` rate, provider, pair,
publication/receipt timestamps, latency, source type, stale state, and cache state.
Redis keys use `gigveyro:<env>:fiat:<provider>:USD:TJS`. Cache TTL (default six
hours) is independent from maximum quote age (default four days, allowing weekends
and holidays). The maximum age is evaluated from the upstream publication time.

Malformed, zero, negative, non-finite, or out-of-bounds values are rejected. An NBT
availability failure can trigger a dated lookback; throttling, timeout, malformed XML,
and permanent pair errors remain explicit. An old primary quote triggers the
secondary policy. No stale quote is relabeled as live. If both sources are available,
their deviation is reported in basis points; crossing the configured threshold marks
diagnostics degraded but does not average or replace the authoritative primary.

Temporary provider failure does not make the web container unready. It makes the
rate diagnostics degraded/unavailable and rate-sensitive Deal acceptance returns a
generic 503. `/health/live` remains independent from external FX availability.

## Deal snapshots and activation

Set `EXCHANGE_RATE_PROVIDER_TYPE=business` to activate the composed provider.
Development-only configured/fallback providers remain available explicitly and are
never presented as live fiat data.

The current architecture fixes a rate when a USER accepts an available Deal. At that
point the immutable `exchange_rate`, calculated `amount_usdt`, source, source
timestamp, policy version, and mode are persisted. Existing rows are not recalculated;
the nullable metadata columns preserve compatibility for historical rows created
before migration `0020`.

No HTML/P2P scraping, private exchange API, trading, payout, withdrawal, or private
key operation is part of this integration.
