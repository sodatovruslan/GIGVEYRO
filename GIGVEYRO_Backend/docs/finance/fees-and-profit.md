# Owner fees and profit accounting

## Business model and safe scope

Fee configuration is versioned and owned exclusively by OWNER. Every new deployment starts with policy version 1 active and all components disabled, so existing financial behavior remains unchanged until OWNER explicitly creates, previews, and activates a later policy.

The policy contains deal, fiat-conversion, withdrawal, and merchant components. Only the managed TJS/RUB conversion component is currently enforceable. Deal payer semantics are not defined by the present workflow, and merchant withdrawals have no request idempotency contract and no real payout execution. Those components therefore remain architecture-only and cannot be activated. This prevents hidden or arbitrary charges.

## Versioning and immutable snapshots

Policies move `draft → active → retired`. There is exactly one active policy. Active and retired records are never edited. Activation retires the previous policy before activating the next under row locks.

Each new fiat conversion stores:

- fee-policy version;
- source and destination currencies;
- source amount;
- untouched NBT reference rate;
- gross destination amount at the reference rate;
- fee amount in destination currency;
- net destination amount;
- effective destination-units-per-source-unit rate.

The associated `fee_snapshots` row records the component bps, fixed/min/max outcome, payer, gross, fee, net, reference rate, and effective rate. A unique source/type constraint prevents a second snapshot for the same operation. Finalized snapshots are append-only.

## Calculation and rounding

`FeeCalculator` is pure and deterministic. It does not access the database. All values use `Decimal` and `NUMERIC(20,8)`; binary floats are rejected by fee-policy request schemas. Percentage fees use basis points (`100 bps = 1%`) and `ROUND_HALF_UP` to eight fractional digits. Fixed fee is added after percentage fee, then optional minimum and maximum bounds are applied. Invalid, non-finite, negative, over-50% bps, inverted bounds, and fee-greater-than-gross inputs fail closed.

For a conversion:

```text
gross_destination = round(source_amount × reference_rate)
fee = FeeCalculator(gross_destination, active_conversion_component)
net_destination = gross_destination - fee
effective_rate = net_destination / source_amount
```

When the component is disabled, fee is exactly zero, destination output and legacy `exchange_rate` remain unchanged, and the operation still snapshots the active policy version.

## Profit ledger versus balances

One positive charged fee creates exactly one immutable `owner_profit_entries` row. Profit is business recognition, not a wallet mutation:

- owner profit ledger: what the business earned;
- internal wallets: platform liabilities and controlled balances;
- external Bybit treasury: funds held by an external exchange account.

These concepts are never merged. Bybit remains authenticated read-only, Binance Private remains unconfigured, and `PAYOUT_ENABLED=false` remains mandatory.

## Idempotency, locking, and invariants

Fiat conversion retains actor-scoped idempotency and locks both managed currency balances in deterministic currency order. It checks idempotency before and after acquiring the balance locks. The active policy is held with a shared row lock for the transaction; policy activation requires exclusive policy locks. Thus an operation uses one complete policy version even if activation races with it.

Database uniqueness guarantees one conversion per actor/idempotency key, one fee snapshot per source/type, and one profit entry per snapshot and source/type. The transaction atomically includes balance changes, paired fiat-ledger entries, fee snapshot, profit recognition, audit, notification, and realtime outbox work. Rollback removes all of them together.

Financial invariants:

- managed balances never become negative;
- the source debit is unchanged;
- destination credit equals snapshot net;
- snapshot gross equals fee plus net;
- retries cannot duplicate fee or profit;
- policy changes never recalculate historical rows;
- profit recognition does not create spendable cash.

## OWNER API and UI

OWNER-only endpoints expose the active policy, draft creation, activation, backend-authoritative preview, profit summaries, and filtered paginated profit history. USER and MERCHANT receive 403 and cannot view Owner revenue. Audit actions record policy creation, activation, and component disablement with safe before/after versions and decimal strings.

The `/owner/fees` UI supports RU, EN, and TG; semantic theme tokens preserve Light, Dark, and System modes. It clearly marks architecture-only components, requires a backend preview before activation, and separates profit from treasury. Actual conversion responses expose gross, fee, net, reference rate, effective rate, and policy version.
