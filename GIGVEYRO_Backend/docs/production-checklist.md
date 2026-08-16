# Production Deployment Checklist — GIGVEYRO Backend

- [ ] `APP_ENV` set to `production`.
- [ ] `DEBUG` set to `false`.
- [ ] Strong `JWT_SECRET_KEY` configured (>= 32 characters).
- [ ] PostgreSQL `DATABASE_URL` configured with SSL/secure credentials.
- [ ] Explicit non-wildcard `CORS_ALLOWED_ORIGINS` specified.
- [ ] `ALLOWED_HOSTS` configured with exact domain names.
- [ ] `PAYOUT_ENABLED` remains `false` until external gateway security verification is completed.
- [ ] Database backup executed before running `alembic upgrade head`.
- [ ] Shared rate-limiter (e.g. Redis) planned if scaling to multi-instance/multi-worker process deployments.
