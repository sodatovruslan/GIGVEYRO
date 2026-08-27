# Managed fiat wallets

GIGVEYRO keeps managed fiat balances separate from the existing USDT settlement wallets. This stage supports `TJS` and `RUB` for `USER` accounts only. It does not change deal settlement, deposits, withdrawals, merchant balances, insurance, or frozen/held USDT accounting.

## Authority and permissions

- `OWNER` may allocate TJS or RUB to an active USER and may convert that USER's balance in either direction.
- `USER` may read their own balances, ledger, and conversion history. There is no USER mutation or self-conversion endpoint.
- `MERCHANT` has no managed-fiat access.
- Allocations retain the existing administrative managed-allocation semantics. No platform treasury was invented for this stage.

The backend is authoritative. The frontend never calculates or mutates a balance locally; after a realtime event it refetches the relevant REST resources.

## Storage and ledger

`fiat_wallet_balances` stores one `Numeric(20, 8)` row per `(account_id, currency)`. Missing rows are returned as read-only zero balances and are created transactionally only when a mutation needs them.

`fiat_ledger_entries` is append-only and records the signed amount, balance before/after, actor, idempotency key, reference, and one of:

- `owner_allocation`
- `conversion_debit`
- `conversion_credit`

`fiat_conversions` stores an immutable conversion snapshot, including both balance transitions, source and destination amounts, normalized rate, NBT publication time, provider, mode, policy version, initiator, comment, and idempotency key.

## Rate policy

The National Bank of Tajikistan (NBT) public XML feed is the authoritative source. Its RUB row quotes TJS for the row's declared `Nominal`; the provider first normalizes `Value / Nominal` to obtain TJS per one RUB.

Conversion rates always mean **destination units per one source unit**:

- RUB to TJS uses the normalized official rate directly.
- TJS to RUB uses its Decimal inverse after nominal normalization.

Rates use deterministic eight-decimal rounding and configurable broad sanity bounds. The current policy has zero fee, markup, and spread. A stale, malformed, or unavailable authoritative quote fails closed with `503`; no hardcoded or Binance/Bybit/P2P fallback is used.

Preview is read-only. Confirmation obtains the backend quote again and persists the final rate snapshot, so the frontend-provided preview is never trusted as financial input.

## Atomicity, idempotency, and concurrency

Allocation and conversion lock the USER's currency rows in stable order. Conversion validates the source balance under the lock, debits source, credits destination, writes both ledger entries, conversion history, audit, notification, and realtime outbox work in the request-scoped database transaction. Any failure rolls the operation back.

OWNER mutations require an actor-scoped idempotency key. An exact retry returns the original logical result without another balance change, audit entry, notification, or realtime event. Reusing a key with a different payload returns `409`.

Database constraints prevent negative balances and duplicate ledger/conversion references. Independent-session concurrency tests cover competing conversions, allocation racing conversion, and simultaneous retries with the same idempotency key.

## Audit, notifications, and realtime

Server-side audit actions are `fiat.allocate` and `fiat.convert`. Metadata contains only operational IDs, currencies, amounts, target account ID, and rate source/mode.

The target USER receives a `FIAT_BALANCE_UPDATED` notification. `fiat.allocated` and `fiat.converted` realtime events go only to that USER and the acting OWNER, contain no balance value, and trigger REST refetch. MERCHANT and unrelated USER accounts are not recipients.

## API surface

OWNER:

- `GET /owner/accounts/{account_id}/fiat-wallets`
- `POST /owner/accounts/{account_id}/fiat-wallets/allocate`
- `POST /owner/fiat-conversions/preview`
- `POST /owner/accounts/{account_id}/fiat-conversions`
- `GET /owner/fiat-conversions`
- `GET /owner/accounts/{account_id}/fiat-wallets/ledger`

USER read-only:

- `GET /fiat-wallets`
- `GET /fiat-wallets/ledger`
- `GET /fiat-wallets/conversions`

There is intentionally no USER conversion endpoint.
