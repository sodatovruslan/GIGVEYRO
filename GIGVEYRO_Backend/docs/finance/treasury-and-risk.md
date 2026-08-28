# Treasury and risk controls

## Accounting definitions

Treasury monitoring separates assets, liabilities, exposure, and profit. USER liability is the sum of every USDT user wallet's available, insurance, and frozen buckets. MERCHANT liability is available plus held. Frozen balances and pending withdrawals are subsets of those totals and are displayed as exposure breakdowns; they are never added again to required reserve.

Deal exposure includes only `accepted`, `payment_pending`, and `disputed` deals, whose USDT is still frozen. Withdrawal exposure includes `pending` and `approved` requests, whose amount remains held. Completed/cancelled/expired deals and paid/rejected/cancelled withdrawals do not count.

Owner profit is accounting income from the immutable profit ledger. It does not reduce liability, credit a wallet, or increase external reserve. Managed TJS/RUB balances remain separate fiat obligations and are not silently converted into USDT exposure.

## External reserve and coverage

Bybit is read through the existing signed GET-only client. No trade, order, transfer, withdrawal, or payout method is introduced. The eligible reserve is observed available USDT (falling back to wallet balance when Bybit does not provide an available value). USDC is displayed separately and is not treated as 1:1 USDT. Therefore combined stable reserve is intentionally undefined.

```text
total_liability = user_liability + merchant_liability
required_reserve = total_liability * minimum_reserve_ratio_bps / 10000
coverage_ratio = observed_external_usdt / total_liability
surplus = max(external_usdt - required_reserve, 0)
deficit = max(required_reserve - external_usdt, 0)
```

All arithmetic uses `Decimal`, `NUMERIC(20,8)`, and deterministic `ROUND_HALF_UP`. An external snapshot is an observation, not a locked or transactionally authoritative exchange balance. Bybit can change outside GIGVEYRO.

## Freshness and statuses

`HEALTHY`, `WARNING`, and `CRITICAL` require a connected provider and an observation no older than the active policy limit. Missing data is `UNKNOWN`; expired data is `STALE`. Stale data can never report healthy. A Bybit outage does not affect `/health/live`, but reserve-dependent enforcement fails closed with `RESERVE_DATA_STALE` when explicitly enabled.

## Versioned policy and enforcement

Risk policies move `draft -> active -> retired`. Migration 0023 seeds version 1 with monitoring active and every enforcement switch disabled. Deployment therefore preserves legacy behavior.

Configurable rules cover reserve coverage, maximum single deal, per-user frozen exposure, pending withdrawals, total open deal exposure, minimum external USDT, and maximum observation age. Draft preview uses the same snapshot and decision services as enforcement.

Deal acceptance and merchant withdrawal creation are the only enforcement points. Their checks run inside the existing financial DB transaction. A PostgreSQL transaction advisory lock serializes enabled checks and the subsequent internal mutation, limiting internal TOCTOU races. External Bybit state cannot be locked; freshness and fail-closed behavior are the explicit boundary.

Risk checks are read-only and never move money. `PAYOUT_ENABLED=false` remains the safe default. Binance Private remains unconfigured.
