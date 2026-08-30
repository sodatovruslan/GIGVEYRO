# GIGVEYRO production deployment

This document covers configuration and release order. Container and Nginx runtime validation is still mandatory before staging or production deployment.

## Configuration

Copy `GIGVEYRO_Backend/.env.production.example` to an untracked secret store or deployment environment. Never commit the resulting file. Process environment variables override dotenv values; verify the effective environment in the service manager.

Required production boundaries:

- `APP_ENV=production`, `DEBUG=false`, `DOCS_ENABLED=false`;
- dedicated PostgreSQL and Redis URLs, neither pointing at localhost;
- unique, rotated JWT, TOTP encryption, metrics, and provider secrets;
- explicit HTTPS CORS origins and public allowed hosts;
- secure HttpOnly SameSite cookies through the same-origin Next.js BFF;
- `REALTIME_BROKER=redis` and `RATE_LIMIT_FAIL_MODE=closed`;
- `PAYOUT_ENABLED=false`, `PAYOUT_PROVIDER_MODE=disabled`, `PAYOUT_SIMULATION_ENABLED=false`, and `BYBIT_WRITE_ENABLED=false`.

The local development contract is `APP_ENV=development` and `DEBUG=true`. A value such as `DEBUG=release` is invalid because `DEBUG` is a boolean.

## Release order

1. Freeze deploys and record the current Git SHA and Alembic revision.
2. Run all backend and frontend gates in `release-checklist.md`.
3. Take a custom-format PostgreSQL backup and restore it into an isolated database.
4. Verify backup integrity and migration `0019 -> 0020 -> 0021 -> 0022 -> 0023 -> 0024 -> 0025` on disposable PostgreSQL.
5. Build immutable images. Run the one-shot `migrate` service, then backend, worker, frontend, and Nginx.
6. Complete `docker-runtime-checklist.md`; do not deploy while that checklist is incomplete.
7. Validate health, authenticated routes, BFF cookies, WebSocket Upgrade, ARQ heartbeat, metrics access, and log redaction.

The repository Compose file publishes only Nginx. `/api/*` goes through the Next.js BFF; `/api/v1/ws` is the direct WebSocket path to FastAPI. Use `nginx/tls.conf.example` as a TLS pattern and enable HSTS only after HTTPS is verified.

## Secrets and networking

Use a secret manager or orchestrator secrets, not image build arguments. Restrict PostgreSQL, Redis, metrics, and backend ports to the private network. Configure the trusted proxy CIDR/IP explicitly. Production egress must use a documented static IP before requesting any exchange write allowlisting.

See also: `backup-restore.md`, `rollback.md`, and `bybit-write-prerequisites.md`.
