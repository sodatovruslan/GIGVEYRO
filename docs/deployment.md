# GIGVEYRO Production Deployment Guide

## Prerequisites

- Docker 24+ and Docker Compose v2
- Git
- Access to server with 2GB+ RAM, 20GB+ disk
- PostgreSQL credentials (or managed PostgreSQL)
- Redis (or managed Redis)

---

## First Deployment

### 1. Clone and Configure

```bash
git clone <your-repo> gigveyro
cd gigveyro
```

### 2. Create Environment File

```bash
cp GIGVEYRO_Backend/.env.example GIGVEYRO_Backend/.env
```

Edit `.env` with your values. **Minimum required for production**:

```env
APP_ENV=production
DEBUG=false
DATABASE_URL=postgresql+asyncpg://user:STRONG_PASS@your-db-host:5432/gigveyro
JWT_SECRET_KEY=<64-char random secret>   # python -c "import secrets; print(secrets.token_hex(32))"
REDIS_URL=redis://your-redis-host:6379/0
CORS_ALLOWED_ORIGINS=["https://yourdomain.com"]
ALLOWED_HOSTS=["yourdomain.com"]
PAYOUT_ENABLED=false                      # KEEP FALSE until provider is verified
DOCS_ENABLED=false                        # Disable Swagger in production
```

### 3. Take Pre-Deploy Backup (existing data)

```bash
./scripts/backup_db.sh
```

### 4. Run Migrations

```bash
cd GIGVEYRO_Backend
alembic upgrade head
cd ..
```

### 5. Build and Start

```bash
docker compose build
docker compose up -d
```

### 6. Verify

```bash
# Health check
curl http://localhost:8000/health/ready

# Check all services
docker compose ps

# Check logs
docker compose logs --tail=50
```

---

## Subsequent Deployments

```bash
# 1. Backup database
./scripts/backup_db.sh

# 2. Pull latest code
git pull

# 3. Run migrations (before starting new app)
cd GIGVEYRO_Backend && alembic upgrade head && cd ..

# 4. Build new images
docker compose build backend worker

# 5. Rolling restart (zero-downtime if load balanced)
docker compose up -d --no-deps backend worker

# 6. Verify
curl http://localhost:8000/health/ready
```

---

## Environment Variable Strategy

### Backend Runtime Env

All config via environment variables or `.env` file. **No secrets in image**.

```
                    ┌─────────────────┐
docker-compose.yml  │  env_file: .env │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  Backend App    │
                    │  pydantic-settings reads env
                    └─────────────────┘
```

### Frontend Runtime Env

```
NEXT_PUBLIC_API_URL    — Browser-visible backend URL (injected at runtime)
BACKEND_URL            — Server-side only (frontend → backend via internal network)
```

**Note**: `NEXT_PUBLIC_*` variables are embedded at **build time** in Next.js. 
For truly runtime env, use a server-side API route that reads `process.env`.

---

## WebSocket Scaling Note

**Current**: `uvicorn --workers 1` (single process)

The `InMemoryRealtimeBroker` is process-local. Running multiple uvicorn workers will split WebSocket connections across processes, breaking real-time event delivery.

**Future scaling path**:
1. Codex implements Redis-backed `RedisBroker`
2. Switch to `RedisBroker` in `app/realtime/runtime.py`
3. Increase `WEB_CONCURRENCY` env var
4. Or: use multiple backend replicas behind Nginx

---

## Production Checklist

- [ ] `APP_ENV=production`
- [ ] `DEBUG=false`
- [ ] `JWT_SECRET_KEY` ≥ 32 chars, random, not `CHANGE_ME`
- [ ] `DATABASE_URL` points to production DB (not localhost)
- [ ] `REDIS_URL` configured
- [ ] `CORS_ALLOWED_ORIGINS` — no wildcards
- [ ] `ALLOWED_HOSTS` — exact domain names
- [ ] `PAYOUT_ENABLED=false` (until external gateway verified)
- [ ] `DOCS_ENABLED=false` (no Swagger in production)
- [ ] Database backup taken before deployment
- [ ] `alembic upgrade head` run successfully
- [ ] `/health/ready` returns 200
- [ ] Nginx configured with WebSocket upgrade headers
- [ ] TLS certificates configured on Nginx
- [ ] Sentry DSN configured (optional)

---

## Backup Schedule

Set up a daily cron job:

```cron
0 2 * * * /path/to/gigveyro/scripts/backup_db.sh /mnt/backups 2>&1 | logger -t gigveyro-backup
```

Default retention: 30 days (`BACKUP_RETAIN_DAYS=30`).

---

## Nginx Configuration

See `nginx/nginx.conf` for the full template.

**Critical for WebSocket** (Codex realtime):
```nginx
location /ws/ {
    proxy_set_header Upgrade    $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout  3600s;
}
```
