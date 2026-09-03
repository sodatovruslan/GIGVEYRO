# Production Deployment Checklist — GIGVEYRO Backend

- [ ] `APP_ENV` set to `production`.
- [ ] `DEBUG` set to `false`.
- [ ] Strong `JWT_SECRET_KEY` configured (>= 32 characters).
- [ ] PostgreSQL `DATABASE_URL` configured with SSL/secure credentials.
- [ ] Explicit non-wildcard `CORS_ALLOWED_ORIGINS` specified.
- [ ] `ALLOWED_HOSTS` configured with exact domain names.
- [ ] `PAYOUT_ENABLED` remains `false` until external gateway security verification is completed.
- [ ] Database backup executed before running `alembic upgrade head`.
- [ ] `REDIS_URL` points to the dedicated production Redis service.
- [ ] Redis-backed distributed rate limiting is enabled with `RATE_LIMIT_FAIL_MODE=closed`.
- [ ] `REALTIME_BROKER=redis`; authenticated cross-process WebSocket delivery is validated.
- [ ] ARQ worker heartbeat and notification/deposit scanner jobs are monitored.
