# Bybit private read-only integration

GIGVEYRO uses the Bybit V5 private API only for OWNER diagnostics of the external treasury account. The client exposes three authenticated `GET` operations:

- `/v5/user/query-api` for API-key mode, permissions, expiry, and IP restriction;
- `/v5/account/info` for account mode;
- `/v5/account/wallet-balance` for an explicit `USDT,USDC` whitelist.

The client has no order, cancel, trade, transfer, withdrawal, payout, or generic request method. `PAYOUT_ENABLED=false` remains independent and mandatory for this stage. Values returned by Bybit are diagnostic external-wallet values and never replace GIGVEYRO ledger balances or backend accounting.

## Authentication and safety gate

Signed GET requests follow the official V5 HMAC-SHA256 scheme: `timestamp + api_key + recv_window + canonical_query`. Credentials are sent only in Bybit authentication headers and are represented in application settings as secret values.

Every diagnostic run calls API-key information first. Account and wallet reads are allowed only when Bybit reports `readOnly=1` and the Wallet permission set does not include `Withdraw`. Otherwise the result is `OVER_PRIVILEGED`, and the run stops before account or balance access.

OWNER may read the normalized diagnostics endpoint. USER and MERCHANT are denied by the existing role dependency. Responses and logs contain no key, secret, raw upstream body, or exact credential error detail. Only a masked key suffix may be returned.

## Configuration

Private access is opt-in even when credentials exist:

```dotenv
BYBIT_PRIVATE_ENABLED=false
BYBIT_API_KEY=
BYBIT_API_SECRET=
BYBIT_RECV_WINDOW_MS=5000
BYBIT_PRIVATE_TIMEOUT_SECONDS=8
BYBIT_PRIVATE_MAX_RETRIES=2
```

Keep actual values only in the local secret environment. Never commit `.env`. Prefer an API key restricted to the backend egress IP, rotate it according to operational policy, and disable it immediately if exposure is suspected.

Binance private access remains unconfigured while KYC is pending; Binance public market data is unaffected.

## Operations

Enable the integration only after verifying the key is read-only. Monitor normalized request, latency, authentication-failure, and rate-limit metrics. Timestamp rejection is reported separately so host clock synchronization can be corrected without weakening the receive window.

Technical references: the official Bybit V5 documentation for [authentication](https://bybit-exchange.github.io/docs/v5/guide), [API-key information](https://bybit-exchange.github.io/docs/v5/user/apikey-info), [account information](https://bybit-exchange.github.io/docs/v5/account/account-info), and [wallet balance](https://bybit-exchange.github.io/docs/v5/account/wallet-balance).
