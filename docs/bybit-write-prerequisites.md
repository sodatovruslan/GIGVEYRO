# Future Bybit write prerequisites

Current policy is read-only. Do not request or enable a write key yet.

Before any write capability is considered:

- complete staging and Docker/Nginx runtime validation;
- obtain a stable, dedicated production egress IP and enforce the Bybit IP allowlist;
- create a separate least-privilege key, never reuse the read-only key;
- keep trading, order, subaccount transfer, and withdrawal permissions disabled unless a separately approved design explicitly needs one;
- complete threat model, dual-control approval, destination/network allowlists, limits, idempotency, reconciliation, alerting, incident kill switch, and independent security review;
- exercise every success, timeout, duplicate, partial failure, replay, and rollback case with non-real funds in an isolated environment;
- require explicit release approval before changing any payout/write flag.

Until all prerequisites are evidenced, the required state is:

```env
PAYOUT_ENABLED=false
PAYOUT_PROVIDER_MODE=disabled
PAYOUT_SIMULATION_ENABLED=false
BYBIT_WRITE_ENABLED=false
```
