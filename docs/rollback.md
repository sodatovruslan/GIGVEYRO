# Rollback runbook

1. Stop traffic or switch it to the last verified application image.
2. Keep payout and every exchange write flag disabled.
3. Capture health, logs, current Git SHA, image digests, and Alembic revision.
4. Prefer an application-only rollback when the previous image is schema-compatible.
5. Never run Alembic downgrade blindly: inspect every downgrade for data loss and rehearse it on a restored disposable database.
6. If restoration is required, obtain explicit incident approval, preserve the failed database, restore the verified pre-release backup to a new database, run integrity checks, then switch the connection atomically.
7. Validate live/ready health, login/session rotation, worker heartbeat, BFF, WebSocket, and financial ledger invariants before reopening traffic.
8. Rotate any potentially exposed secret and document timeline, impact, and follow-up.

Rollback is complete only after monitoring remains healthy through the agreed observation window.
