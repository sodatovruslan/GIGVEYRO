# Controlled payout architecture

## Scope and safety boundary

This stage implements an internal payout control plane. It does not implement or call an
exchange write API. `PAYOUT_ENABLED`, `PAYOUT_SIMULATION_ENABLED`, and the versioned business
policy switch default to `false`; `PAYOUT_PROVIDER_MODE` defaults to `disabled`. Configuration
validation rejects `live` mode because no approved live provider exists.

The existing Bybit private integration remains read-only. `ExchangePayoutProvider` is a separate
interface and has no inheritance, import dependency, or shared implementation with the Bybit
read-only provider. The only implementations are `DisabledPayoutProvider` and the local,
network-free `SimulatedPayoutProvider`.

## Reservation and finalization

The merchant withdrawal remains the source of the financial reservation:

1. Withdrawal creation atomically moves merchant funds from `available` to `held`.
2. Creating a payout intent does not reserve or debit funds again.
3. Rejection or cancellation releases the existing hold once.
4. Authoritative success consumes the existing hold once and creates the existing
   `WITHDRAWAL_PAID` ledger entry.

The unique ledger reference and locked withdrawal/wallet rows make retries idempotent. A payout
is never marked successful merely because execution started or a request was accepted.

## State machine

All status changes go through the central transition validator:

```text
requested -> risk_review -> approved -> queued
                                 |          |
                                 |          -> execution_pending -> executing -> succeeded
                                 |                                      |        -> failed
                                 |                                      -> reconciliation_required
                                 -> awaiting_manual_settlement -> succeeded

risk_review -> rejected
eligible pre-execution states -> cancelled
reconciliation_required -> succeeded | failed
```

Arbitrary jumps and changes after terminal states are rejected. `execution_pending` and
`executing` are never treated as permission to retry an unknown external outcome.

## Immutable intent and approvals

Each withdrawal has at most one payout intent through unique `withdrawal_id` and idempotency-key
constraints. The intent snapshots the parties, asset, exact Decimal amount, network, destination,
fee, approval policy, risk decision, risk policy version, treasury timestamp, provider mode, and
required approval count. Public responses expose a masked destination.

A canonical SHA-256 hash covers the immutable fields. Every control operation verifies the hash.
Each approval stores the same hash and is unique per intent and approver. A changed intent cannot
reuse an approval. Policies support one approval or two distinct Owner approvals above a configured
threshold; automatic approval is intentionally unavailable.

## Risk gates, freshness, and limits

Risk is evaluated when the intent is created, again for approval, and immediately before simulated
or manual settlement. The execution gate uses the current backend-authoritative treasury snapshot.
A stale or unknown reserve produces `RESERVE_DATA_STALE` and blocks execution.

The active versioned payout policy can independently enforce maximum single, daily, hourly,
pending-total, and per-asset exposure. Disabled limits remain observable configuration rather than
implicit behavior. Both the global configuration switch and active business policy switch must be
true; either switch blocks execution.

## Idempotency and concurrency

Payout and withdrawal rows are locked before control transitions. Worker selection uses
`FOR UPDATE SKIP LOCKED` and selects only `queued` intents. Database uniqueness protects payout
creation, approver identity, provider reference, and final ledger settlement. Therefore duplicate
approval, queue, execution, finalization, and reconciliation requests are safe.

A future external provider must accept the immutable payout idempotency key and preserve it across
timeouts. Database locks alone cannot guarantee exactly-once external money movement.

## Failure and reconciliation

Provider outcomes are separated into `succeeded`, `failed`, `pending`, and `unknown`.
Permanent failure is terminal. Pending or unknown outcomes enter `reconciliation_required`; the
worker does not execute them again. Only an explicit status reconciliation may finalize them.
Repeated pending reconciliation remains in that state and leaves held funds unchanged.

The simulator deterministically produces success, failure, pending, or unknown outcomes and assigns
an obviously simulated reference. It performs no network I/O. Manual settlement is a separate
audited path: an Owner first moves an approved payout to `awaiting_manual_settlement`, then records
a non-empty external reference and evidence before internal finalization.

## Audit, notifications, realtime, and access

The append-only payout event timeline and audit log cover intent creation, risk checks, approvals,
rejection, queueing, execution start, simulated success, failure, reconciliation requirement,
reconciliation, and cancellation. Metadata excludes credentials and full destinations.

Owners receive approval/failure/reconciliation notifications; merchants receive their established
withdrawal approved/rejected/completed notifications. Targeted `payout.updated` and
`withdrawal.updated` outbox events prompt clients to refetch authoritative REST state.

Only OWNER routes expose approval, cancellation, queue, reconciliation, manual settlement, and
policy commands. USER and MERCHANT roles cannot execute or mutate payout control state. The live
execute route always returns `LIVE_PAYOUT_NOT_AVAILABLE`.

## Requirements for a future live provider

Live implementation remains explicitly out of scope. Before it can be considered, it requires a
separate security review, provider idempotency guarantees, request signing isolation, allowlisted
destinations and networks, durable send-attempt records, timeout-safe reconciliation, webhook or
poll verification, operational dual control, restricted credentials, incident runbooks, and an
independent real-money rollout approval. Enabling config alone must never make live writes possible.
