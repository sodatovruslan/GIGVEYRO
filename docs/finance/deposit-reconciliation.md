# Unmatched deposit reconciliation

The TRC20 scanner stores a normalized transfer as unmatched when the current deterministic correlation rules find no deposit intent, or as ambiguous when more than one intent matches. The OWNER workflow is an investigation tool; it is not a force-credit capability.

## States and actions

- `PENDING`: awaiting investigation.
- `REPROCESSED`: current deposit state was checked again, but no unique safe match existed.
- `IGNORED`: terminal non-financial decision with a required reason. Reopening is not supported.
- `CREDITED`: terminal financial result after the normal deposit credit path completed.
- `LINKED` and `FAILED` are reserved explicit states; successful link and credit are currently atomic, so no durable intermediate link is exposed.

Only OWNER routes can list details or run `link`, `reprocess`, and `ignore`. USER and MERCHANT access is rejected. Details expose normalized facts, masked sender address, candidate intent references, and action history—never provider credentials or raw provider payloads.

## Candidate and link policy

Candidates use current deterministic facts only: USDT asset, TRC20 network, destination address, open unexpired deposit state, and exact amount ordering. There is no fuzzy match. Multiple exact candidates require an explicit OWNER choice.

Before link, the backend locks both the unmatched row and selected deposit, then validates:

- supported USDT/TRC20 contract and network;
- matching destination address and exact decimal amount;
- provider finality and required confirmations;
- unexpired `WAITING` deposit;
- transfer and deposit have not already been linked or credited;
- provider event identity is not attached to another deposit.

The existing `DepositService.ingest_transaction_event` remains the only credit source. It creates the idempotent wallet ledger entry, transitions the deposit, and emits the existing semantic `deposit.credited` notification. The frontend never computes or applies credit.

The current expiry policy is based on the deposit intent's current expiry and status. Manual reconciliation cannot override it, even if a transfer block timestamp predates expiry. Any future override must be a separate audited business capability.

Amount mismatch is never rounded or partially credited. The API returns observed, expected, and decimal difference data for investigation, while link rejects with `AMOUNT_MISMATCH`.

## Reprocess and ignore

Reprocess applies the same current candidate rules. One exact safe candidate proceeds through the authoritative link/credit path; multiple matches return `AMBIGUOUS_MATCH`; none returns `NO_MATCH`. It cannot edit chain facts, bypass finality, or create transfers.

Ignore requires a reason, creates no ledger or balance mutation, and is terminal. Its audit record and reconciliation action remain available to OWNER.

## Idempotency, concurrency, and audit

Each command requires an actor-scoped idempotency key. A PostgreSQL transaction advisory lock serializes the initial key lookup, and `(actor_account_id, idempotency_key)` is unique. Retrying the same payload replays the stored result without another ledger entry, notification, or reconciliation audit.

Row locks serialize OWNER actions, scanner metadata refresh, and deposit credit. Existing database uniqueness on deposit provider event identity and wallet ledger idempotency is the final double-credit guard. Tests cover two links to two targets, ignore versus link, scanner rediscovery versus link, and worker credit versus link; the invariant is at most one credited deposit and one exact ledger mutation.

Audit actions are `deposit_reconciliation.linked`, `.reprocessed`, `.ignored`, and `.credit_succeeded`. Metadata contains only actor context, internal transfer/deposit IDs, and result code—no external addresses or secrets. Validation failures return stable machine-readable codes and roll back the financial transaction.

Realtime publishes `deposit.updated` only after successful credit. The REST-authoritative client then refetches OWNER unmatched/deposit data and the target USER deposit/wallet data. External Telegram delivery remains outside the financial mutation and cannot roll it back.
