# TronGrid TRC20 Deposit Scanner

## Safety boundary

This integration is read-only. It calls TronGrid only with HTTP `GET` and never holds a TRON
private key. It cannot sign transactions, trade, transfer, withdraw, or execute payouts. The
only supported asset/network pair is the configured official USDT TRC20 contract on TRON.

`PAYOUT_ENABLED=false` and `BYBIT_WRITE_ENABLED=false` remain independent mandatory guards.

## Discovery and finality

For every scan the provider:

1. Reads the latest block number.
2. Reads incoming account TRC20 history with `only_confirmed=true`, `only_to=true`, the exact
   USDT contract, an ascending bounded timestamp window, and fingerprint pagination.
3. Reads each transaction's confirmed event list to obtain `event_index` and `block_number`.
4. Validates Base58Check addresses, contract, decimals, integer raw value, destination, event
   type, and positive amount before returning a normalized event.
5. Computes numeric confirmations as `head - event_block + 1`. Credit still requires the
   existing application confirmation threshold and the event to be finalized.

One transaction may contain multiple `Transfer` events. Persistence therefore uses
`trongrid:<transaction_id>:<event_index>` as the stable idempotency key; `tx_hash` remains a
search/display field. Existing rows are migrated to a `legacy:` identity.

## Cursor and restart behavior

After a complete provider scan and successful database commit, the worker writes the fixed
scan upper timestamp to Redis. The next scan starts at watermark minus
`TRONGRID_SCAN_OVERLAP_SECONDS`. Redis loss or a cold restart replays the full active deposit
intent TTL plus overlap. Database uniqueness and ledger reference idempotency make overlap
replay safe.

The watermark is not advanced when pagination is incomplete, the cursor repeats, the maximum
page count is reached, an upstream response is malformed, or the database transaction fails.

## Configuration

```dotenv
DEPOSIT_PROVIDER_TYPE=trongrid
TRONGRID_API_URL=https://api.trongrid.io
TRONGRID_API_KEY=<secret>
TRONGRID_PAGE_SIZE=100
TRONGRID_MAX_PAGES=10
TRONGRID_MAX_RETRIES=2
TRONGRID_SCAN_OVERLAP_SECONDS=300
USDT_TRC20_DECIMALS=6
```

Production validation requires HTTPS and a non-empty TronGrid API key. The key is sent only in
the `TRON-PRO-API-KEY` header and is never included in logs or diagnostics.

## Failure handling

- `429`: bounded retry honoring a numeric `Retry-After`, then a rate-limit error.
- timeout/network/`5xx`: bounded retry, then a typed unavailable error.
- `401`/`403`: typed authentication/policy error; no retry.
- malformed JSON/envelope/event/cursor: fail closed (or reject only the malformed event when
  the surrounding page is valid).

Logs contain operation/category/count/timing metadata, not API keys, full addresses, or raw
provider payloads. Diagnostics expose only configured/read-only state and last scan outcome.

## Operations

Alert on sustained `deposit_scanner_rate_limits_total`, error growth, missing recent successful
scan diagnostics, or a watermark that stops advancing. Correct the provider/network problem
and allow the next scan to replay the overlap window; do not manually credit deposits. If a
transfer cannot be correlated uniquely, it remains in the existing unmatched/ambiguous owner
workflow for review.

Official references:

- <https://developers.tron.network/docs/get-trc20-transaction-history>
- <https://developers.tron.network/reference/get-trc20-transaction-info-by-account-address>
- <https://developers.tron.network/docs/confirmation-semantics>
- <https://developers.tron.network/reference/rate-limits>
