# GIGVEYRO Database Backup & Restore Guide

## Backup Strategy

**Method**: `pg_dump --format=custom` (compressed, parallel-restore capable)  
**Frequency**: Daily (recommended), plus before every deployment  
**Retention**: 30 days (configurable via `BACKUP_RETAIN_DAYS`)  
**Storage**: Encrypted, access-controlled off-site storage (e.g. S3, GCS)

---

## Quick Start

### Take a Backup

```bash
# Default: saves to ./backups/
./scripts/backup_db.sh

# Custom directory:
./scripts/backup_db.sh /mnt/backups

# With credentials:
POSTGRES_HOST=db.example.com \
POSTGRES_USER=gigveyro_user \
PGPASSWORD=your_password \
./scripts/backup_db.sh /mnt/backups
```

### Restore from Backup

**Always restore to a test database first.**

```bash
# Restore to test DB (safe)
./scripts/restore_db.sh backups/gigveyro_20260101_120000.dump gigveyro_restore_test

# Restore to production (with 5-second cancel window)
POSTGRES_USER=gigveyro_user \
PGPASSWORD=your_password \
./scripts/restore_db.sh backups/gigveyro_20260101_120000.dump gigveyro
```

---

## Automated Daily Backup (cron)

```cron
# Run at 2:00 AM daily, retain 30 days
0 2 * * * POSTGRES_HOST=localhost POSTGRES_USER=gigveyro_user PGPASSWORD=secret \
          /app/scripts/backup_db.sh /mnt/backups \
          >> /var/log/gigveyro-backup.log 2>&1
```

---

## Credential Security

**NEVER** put passwords in:
- Shell scripts (including this one)
- Environment files committed to git
- Docker logs

**Safe methods**:
1. `PGPASSWORD` env var (set in shell, not script)
2. `~/.pgpass` file (chmod 600)
3. PostgreSQL service account (Docker internal network, no password needed)

---

## Backup Verification

Verify backup integrity monthly:

```bash
# Restore to isolated test DB
./scripts/restore_db.sh backups/gigveyro_latest.dump gigveyro_verify

# Connect and check row counts
psql -U gigveyro_user -d gigveyro_verify -c "
SELECT 
    (SELECT COUNT(*) FROM account) AS accounts,
    (SELECT COUNT(*) FROM deal) AS deals,
    (SELECT COUNT(*) FROM deposit) AS deposits,
    (SELECT COUNT(*) FROM merchant_withdrawal) AS withdrawals;
"

# Drop test DB when done
psql -U gigveyro_user -d postgres -c "DROP DATABASE gigveyro_verify;"
```

---

## Alembic Migration Strategy

### Production Deploy Flow

```
1. git pull
2. ./scripts/backup_db.sh          ← Always backup first
3. alembic upgrade head            ← Apply migrations
4. docker compose up -d backend    ← Start new app
```

### Checking Migration Status

```bash
alembic current    # Shows current revision
alembic history    # Shows migration history
alembic check      # Checks if any migrations need to run
```

### Emergency Downgrade

Only for non-destructive migrations. Check migration file before running.

```bash
# Downgrade by 1 revision
alembic downgrade -1

# Downgrade to specific revision
alembic downgrade abc123def
```

**NEVER** run destructive downgrade (DROP TABLE, DROP COLUMN) in production without:
1. Full backup
2. Explicit testing in staging
3. Approval from database administrator
