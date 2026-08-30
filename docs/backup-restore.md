# PostgreSQL backup and restore

Use the PostgreSQL client major version matching the server. Backups use `pg_dump --format=custom`; store them encrypted, off-host, access-controlled, and covered by retention monitoring.

## Backup

Run `scripts/backup_db.sh` with credentials supplied by a secret manager or `.pgpass`. Take a backup before every migration and on a tested schedule. A backup is not accepted until a disposable restore succeeds.

## Restore verification

Restore only to an explicitly named disposable database:

```bash
RESTORE_CONFIRM_TARGET=gigveyro_restore_20260830 \
  ./scripts/restore_db.sh backups/gigveyro.dump gigveyro_restore_20260830
```

The confirmation must exactly match the target. Never point this command at a shared development, staging, or production database.

After restore, verify:

- `alembic_version` is the expected release revision;
- counts and representative IDs match for `accounts`, `wallets`, `ledger_entries`, `deals`, `fee_policies`, `risk_policies`, `payout_policies`, and payout security tables;
- constraints, indexes, enum types, and ownership are present;
- application read-only smoke succeeds against the restored database.

Record backup checksum, PostgreSQL/pg_dump versions, restore duration, verification output, and the operator. Delete only the known disposable database after verification.
