# GIGVEYRO Production Runbook

## Quick Reference — Service URLs

| Service | Internal URL | Health Check |
|---------|-------------|--------------|
| Backend (FastAPI) | `http://backend:8000` | `GET /health/live` |
| Frontend (Next.js) | `http://frontend:3000` | `GET /` |
| PostgreSQL | `postgres:5432` | `pg_isready` |
| Redis | `redis:6379` | `redis-cli ping` |
| Worker (ARQ) | — (process) | Docker container status |

---

## Incident Runbooks

### 🔴 Database Down

**Symptoms**: `/health/ready` returns 503, `database: error`.

**Steps**:
1. Check PostgreSQL container: `docker compose ps postgres`
2. View logs: `docker compose logs postgres --tail=50`
3. Check disk space: `df -h /var/lib/docker`
4. Attempt restart: `docker compose restart postgres`
5. If data corruption suspected:
   - Stop backend and worker: `docker compose stop backend worker`
   - Restore from latest backup: `./scripts/restore_db.sh backups/latest.dump`
   - Restart services: `docker compose start backend worker`
6. After restart, verify: `curl http://localhost:8000/health/ready`

**Prevention**: Ensure `postgres_data` volume is on persistent, backed-up storage.

---

### 🔴 Redis Down

**Symptoms**: Worker jobs fail to enqueue, rate limiter falls back to allow-all, `/health/ready` shows redis error.

**Impact Assessment**:
- Web requests: **continue to work** (Redis error is non-fatal for API)
- Rate limiting: **fails open** (allows all requests)
- Background workers: **cannot process** new jobs
- WebSocket broker: **continues working** (InMemoryBroker, not Redis-dependent)

**Steps**:
1. Check Redis container: `docker compose ps redis`
2. View logs: `docker compose logs redis --tail=50`
3. Check memory: `docker stats redis`
4. Attempt restart: `docker compose restart redis`
5. Verify ARQ reconnects: `docker compose logs worker --tail=20`

---

### 🔴 External Provider Down (TronGrid / Exchange Rate API)

**Impact**: Deposit scanning stops, exchange rate uses cached/fallback value.

**Steps**:
1. Check `/health/diagnostics` for provider status
2. Monitor TronGrid status: https://www.trongrid.io/status
3. Deposit scanner will auto-retry on next cron interval (60s)
4. Exchange rate `FallbackExchangeRateProvider` will use cached value up to TTL
5. If outage is prolonged, set `DEPOSIT_PROVIDER_TYPE=mock` to disable scanning:
   ```bash
   # In .env
   DEPOSIT_PROVIDER_TYPE=mock
   docker compose restart backend worker
   ```
6. Revert when provider recovers

---

### 🔴 Worker Stuck / Outbox Backlog

**Symptoms**: Notifications not sending, outbox count growing, `/metrics` shows high `gigveyro_outbox_pending_total`.

**Steps**:
1. Check worker: `docker compose ps worker`
2. View worker logs: `docker compose logs worker --tail=100`
3. Check ARQ queue in Redis:
   ```bash
   docker compose exec redis redis-cli keys "arq:*"
   ```
4. Restart worker: `docker compose restart worker`
5. If outbox has FAILED entries, they are dead-lettered and will not retry automatically
6. To manually retry dead-letter entries, update their status to PENDING in DB:
   ```sql
   UPDATE notification_outbox SET status = 'pending', attempts = 0
   WHERE status = 'failed' AND created_at > NOW() - INTERVAL '24 hours';
   ```

---

### 🟡 Application Rollback

**Trigger**: New deployment causes errors, need to rollback.

**Steps**:
1. Identify last known-good commit: `git log --oneline -10`
2. Stop services: `docker compose stop backend worker`
3. Build old image: `docker build -t gigveyro-backend:rollback .`
4. Update docker-compose to use rollback image
5. **Alembic downgrade**: Only if migration is reversible and non-destructive:
   ```bash
   # NEVER run destructive downgrade without backup
   alembic downgrade -1
   ```
6. Restart: `docker compose start backend worker`
7. Verify: `curl http://localhost:8000/health/ready`

---

### 🟡 Database Restore Procedure

1. **Stop services** to prevent writes during restore:
   ```bash
   docker compose stop backend worker
   ```
2. **Create backup** of current state (just in case):
   ```bash
   ./scripts/backup_db.sh
   ```
3. **Restore to test database** first:
   ```bash
   ./scripts/restore_db.sh backups/gigveyro_YYYYMMDD_HHMMSS.dump gigveyro_restore_test
   ```
4. **Verify data** in test database
5. **Restore to production** (with confirmation):
   ```bash
   POSTGRES_DB=gigveyro ./scripts/restore_db.sh backups/gigveyro_YYYYMMDD_HHMMSS.dump gigveyro
   ```
6. **Run migrations**:
   ```bash
   alembic upgrade head
   ```
7. **Restart services**

---

### 🟡 Pre-Deployment Checklist

Before every production deployment:

- [ ] `git status` — confirm clean working tree
- [ ] `./scripts/backup_db.sh` — take a DB backup
- [ ] `alembic upgrade head` — run migrations
- [ ] `docker compose build backend frontend` — build new images
- [ ] `docker compose up -d` — deploy
- [ ] `curl http://localhost:8000/health/ready` — verify readiness
- [ ] Check `/health/diagnostics` — verify providers
- [ ] Monitor `docker compose logs --tail=100` — watch for errors

---

## Key Configuration Reference

| Variable | Default | Production Required |
|----------|---------|---------------------|
| `APP_ENV` | `development` | `production` |
| `DEBUG` | `false` | `false` |
| `JWT_SECRET_KEY` | (must set) | 32+ chars, random |
| `DATABASE_URL` | (must set) | PostgreSQL SSL URL |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis service URL |
| `PAYOUT_ENABLED` | `false` | Keep `false` until verified |
| `DEPOSIT_PROVIDER_TYPE` | `mock` | `trongrid` for live |
| `SENTRY_DSN` | `` | Optional — set for monitoring |

---

## Real Money Safety Confirmation

**The following operations are NEVER performed automatically:**
- USDT payout via TRC20
- TRON transaction signing
- Private key operations
- Binance/Bybit withdrawals

**All payout operations require:**
1. `PAYOUT_ENABLED=True` (explicit opt-in)
2. `PAYOUT_PROVIDER_TYPE=external_adapter` (real provider)
3. `PAYOUT_API_KEY` configured
4. Owner manual approval (withdrawal status → APPROVED)

The default `PAYOUT_ENABLED=False` makes all payout jobs no-ops.
