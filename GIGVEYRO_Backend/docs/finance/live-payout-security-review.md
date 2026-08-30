# Live payout provider security review

## Status and boundary

This stage does not enable live payouts. `PAYOUT_ENABLED=false`,
`PAYOUT_PROVIDER_MODE=disabled`, and `BYBIT_WRITE_ENABLED=false` are the safe
defaults. Configuration rejects `live` provider mode and rejects enabling the
write plane. `BybitLivePayoutProvider` contains no HTTP transport and fails with
`BYBIT_WRITE_NETWORK_DISABLED` if execution is called.

The existing Bybit private client remains read-only. Its credentials are never
reused by the future write plane. Future credentials use only
`BYBIT_WRITE_API_KEY` and `BYBIT_WRITE_API_SECRET`, remain environment secrets,
and must never be returned by an API, stored in the database, or logged.

## Official Bybit V5 contract reviewed

- Create withdrawal: `POST /v5/asset/withdraw/create`. The master-UID API key
  must have withdrawal permission, the destination must exist in Bybit's
  address book, and `requestId` is a case-sensitive globally unique 1-32
  alphanumeric identifier. GIGVEYRO maps the immutable payout-intent UUID to
  its 32-character hexadecimal form.
- Withdrawal status/history: `GET /v5/asset/withdraw/query-record`.
- Address book: `GET /v5/asset/withdraw/query-address`.
- Coin and network metadata: `GET /v5/asset/coin/query-info` supplies chain
  availability, minimum/maximum, precision, fixed fee, and percentage fee.
- API key status: `GET /v5/user/query-api` supplies `readOnly`, permissions,
  bound IPs, and expiry information.
- Internal transfer endpoints were reviewed but are not the payout mechanism.

Official sources:

- <https://bybit-exchange.github.io/docs/v5/asset/withdraw>
- <https://bybit-exchange.github.io/docs/v5/asset/withdraw/withdraw-record>
- <https://bybit-exchange.github.io/docs/v5/asset/withdraw/withdraw-address>
- <https://bybit-exchange.github.io/docs/v5/asset/coin-info>
- <https://bybit-exchange.github.io/docs/v5/user/apikey-info>
- <https://bybit-exchange.github.io/docs/v5/guide>
- <https://bybit-exchange.github.io/docs/v5/rate-limit>
- <https://bybit-exchange.github.io/docs/v5/error>
- <https://bybit-exchange.github.io/docs/v5/asset/transfer/create-inter-transfer>
- <https://bybit-exchange.github.io/docs/v5/asset/transfer/inter-transfer-list>

The future key must be a master-UID key with only the documented Wallet
withdrawal capability needed by the selected flow. Trading, orders, positions,
derivatives, options, spot trade, and unrelated transfer capabilities are not
allowed. A verified fixed-IP restriction is mandatory. Permission and IP
checks are explicit readiness gates; their absence cannot be inferred as safe.

## Request construction and fee semantics

Only USDT on the internally named `TRC20` network is enabled. It maps to
Bybit's documented `TRX` chain code. Arbitrary assets, networks, hosts, and API
paths are rejected. TRON destinations are checked with Base58Check, including
the `0x41` network byte and checksum, rather than by regex alone.

The dry-run request uses on-chain mode (`forceChain=1`), `accountType=UTA`, and
`feeType=0`. With `feeType=0`, the requested amount is the recipient amount.
When Bybit publishes a percentage fee, expected handling fee is
`amount / (1 - percentage) * percentage + fixed_fee`; otherwise it is the fixed
fee. Total treasury impact is recipient amount plus expected fee. Unknown,
disabled, stale, below-minimum, above-maximum, or over-precision metadata fails
closed. Metadata must be reread immediately before any future send.

Bybit V5 POST signatures use
`timestamp + apiKey + recvWindow + exactJsonBody`, HMAC-SHA256 lowercase hex.
The timestamp must satisfy the documented receive window. Unit tests use dummy
credentials and canonical JSON only; no production credential is read.

## GIGVEYRO controls

The live-readiness service evaluates every gate centrally:

- global payout kill switch and live provider mode;
- separately enabled and configured write credentials;
- verified withdrawal permission and fixed-IP allowlist;
- enabled immutable beneficiary destination and exact asset/network binding;
- enabled network allowlist;
- business payout switch;
- existing reserve/risk policy and fresh treasury data;
- at least two distinct OWNER approvals for all future live payouts;
- verified reconciliation support;
- availability of an approved write transport.

The final transport check is hardcoded unavailable in this stage, so readiness
cannot become true. The OWNER UI is diagnostic only and has no live enable or
send action.

Destinations are immutable. The database stores the full address only for a
future secured execution lookup; list APIs expose only a mask and SHA-256
fingerprint. Changing a destination means disabling it and creating another.
Creating and disabling are OWNER-only and audited. Approval hashes already bind
amount, asset, network, full destination, fee snapshot, risk and approval policy
versions, provider mode, live provider identity, and idempotency key. The provider
identity is added to the hash for live mode without invalidating historical
disabled/simulated hashes. Any bound-field mutation invalidates approval.

Existing payout limits and risk policy remain authoritative. The future
pre-send gate must calculate observed eligible reserve minus recipient amount
minus provider fee and reject a result below the required reserve. No frontend
financial calculation is authoritative.

## Retry, unknown result, and reconciliation

Bybit's `requestId` is the provider idempotency key. A timeout after a future
write is not treated as failure and must not cause an automatic retry. The
intent moves to `RECONCILIATION_REQUIRED`; the system queries withdrawal
history by known identifiers until it can establish a terminal outcome. The
write key may be needed for those reads, but permission has not been requested
in this stage. Provider rate-limit, duplicate, signature, IP, permission,
compliance, and timeout codes remain distinct sanitized failure categories.

An emergency stop blocks every new execution immediately. It cannot reverse an
external request already accepted by Bybit; an in-flight unknown request must
be reconciled.

## Requirements before a later enablement review

1. Complete an independent security and operations review of the write path.
2. Provision a separate master-UID key with withdrawal-only least privilege and
   a fixed-IP allowlist; never expand the current read-only key.
3. Verify Bybit address-book records and the internal immutable allowlist out of
   band.
4. Implement an approved fixed-host transport with redacted telemetry and no
   endpoint injection.
5. Implement and test live withdrawal-history reconciliation, including unknown
   outcomes, without blind retry.
6. Prove dual OWNER approval, fresh metadata, fresh treasury, payout limits,
   post-fee reserve, idempotency, concurrency, and emergency-stop behavior in a
   non-production environment.
7. Perform a separate explicit real-money authorization stage. This document is
   not such authorization.
