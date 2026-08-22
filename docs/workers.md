# GIGVEYRO Background Workers

## Overview

GIGVEYRO uses **ARQ** (Async Redis Queue) for background job processing.

**Why ARQ?**
- Native `asyncio` — zero friction with async SQLAlchemy and FastAPI
- Redis-backed queue — same Redis we use for rate limiting
- Built-in cron scheduling
- Minimal dependencies
- Graceful SIGTERM shutdown
- No Celery/gevent complexity

---

## Worker Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   Docker Worker Container                │
│                                                         │
│  python worker_entrypoint.py                            │
│  → arq app.workers.arq_settings.WorkerSettings          │
│                                                         │
│  ┌─────────────┐  ┌─────────────┐  ┌───────────────┐  │
│  │  Notif      │  │  Deposit    │  │  Deal Expiry  │  │
│  │  Outbox     │  │  Scanner    │  │  (5 min)      │  │
│  │  (30s)      │  │  (60s)      │  │               │  │
│  └─────────────┘  └─────────────┘  └───────────────┘  │
│  ┌─────────────────────────────────────────────────┐   │
│  │  Payout Orchestrator (10 min) — DISABLED BY DEF │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
         │                    │
         ▼                    ▼
    PostgreSQL              Redis (ARQ Queue)
```

---

## Jobs

### 1. Notification Outbox (`process_notification_outbox`)

**Schedule**: Every 30 seconds  
**Source**: `app/workers/jobs/notification_outbox.py`  
**Wraps**: `NotificationService.process_outbox_batch()`

- Picks up pending `NotificationOutbox` entries
- Dispatches via Telegram provider
- Respects max_attempts and dead-letter state
- Idempotent: already-processed entries filtered by status

**Configuration**:
- `OUTBOX_BATCH_SIZE=50` — entries per batch

---

### 2. Deposit Scanner (`scan_deposits`)

**Schedule**: Every 60 seconds  
**Source**: `app/workers/jobs/deposit_scanner.py`  
**Wraps**: `DepositService.scan_and_correlate_deposits()`

**STRICT READ-ONLY** — no private keys, no signing.

- Fetches on-chain TRC20 transfers via TronGrid API
- Correlates with active deposit intents
- Records unmatched/ambiguous transfers
- Idempotent via `tx_hash` DB unique constraint
- Uses distributed lock (prevents concurrent runs)
- **Automatically skipped** when `DEPOSIT_PROVIDER_TYPE=mock`

**Configuration**:
- `DEPOSIT_PROVIDER_TYPE=trongrid` — enables real scanning
- `TRONGRID_API_KEY` — required for real scanning
- `SCAN_INTERVAL_SECONDS=60` — scan frequency

---

### 3. Deal Expiry (`expire_stale_deals`)

**Schedule**: Every 5 minutes  
**Source**: `app/workers/jobs/deal_expiry.py`

- Transitions `AVAILABLE` deals past `DEAL_TTL_MINUTES` to `EXPIRED`
- Uses existing `DealStatus.EXPIRED` — no new statuses
- Atomic bulk UPDATE — no N+1 queries
- No financial side effects (AVAILABLE deals have no locked funds)

---

### 4. Payout Orchestrator (`process_approved_payouts`)

**Schedule**: Every 10 minutes  
**Source**: `app/workers/jobs/payout_orchestrator.py`  
**Status**: 🚫 **DISABLED BY DEFAULT**

- **NO-OP** when `PAYOUT_ENABLED=False` (default)
- When enabled: finds APPROVED withdrawals → submits to payout provider
- Idempotent: checks existing payout_ref before submitting
- **Requires explicit opt-in**: `PAYOUT_ENABLED=True` + real provider config

---

## Running the Worker

### Development
```bash
cd GIGVEYRO_Backend
pip install -r requirements.txt
python worker_entrypoint.py
```

### Docker
```bash
docker compose up worker
```

### Direct ARQ CLI
```bash
arq app.workers.arq_settings.WorkerSettings
```

---

## Distributed Locks

Singleton jobs (deposit scanner) use Redis distributed locks to prevent concurrent execution when multiple worker processes run:

```python
async with DistributedLock(redis, "deposit_scanner_singleton", ttl_ms=70_000) as acquired:
    if not acquired:
        return  # Another worker is running this job
    await _run_scan()
```

Lock is released on job completion or automatically expires after TTL.

---

## WebSocket Isolation Note

The ARQ worker runs in a **separate process** from the FastAPI web server.  
It does **NOT** share `InMemoryRealtimeBroker` state with the web process.

This is intentional:
- Workers handle background I/O, not real-time events
- Real-time events triggered by worker jobs should be written to the `realtime_outbox` table
- The web process polls this table and dispatches via WebSocket

**Horizontal scaling**: When switching to `RedisBroker`, multiple web processes can share WebSocket state. This requires Codex's Redis broker implementation.

---

## Monitoring

Worker metrics exposed at `/metrics` (Prometheus):

| Metric | Description |
|--------|-------------|
| `gigveyro_worker_jobs_total{job,status}` | Job executions by name and outcome |
| `gigveyro_outbox_pending_total` | Pending notification outbox gauge |
| `gigveyro_deposit_scan_errors_total` | Deposit scanner provider errors |
| `gigveyro_provider_errors_total{provider}` | External provider failures |
