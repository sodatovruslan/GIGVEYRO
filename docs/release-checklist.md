# Release checklist

## Before build

- [ ] Approved Git SHA and clean, reviewed diff.
- [ ] No `.env`, credentials, private keys, authorization headers, or database dumps tracked.
- [ ] `APP_ENV=production`, `DEBUG=false`, explicit HTTPS CORS and public hosts.
- [ ] JWT/TOTP/metrics secrets are unique and stored outside Git.
- [ ] Dedicated PostgreSQL/Redis endpoints; Redis uses persistence and `noeviction`.
- [ ] Secure cookies, same-origin BFF, trusted proxy boundary, and TLS plan reviewed.
- [ ] All payout/write flags remain off.

## Gates

- [ ] Backend `pytest` and `ruff check .` pass.
- [ ] Frontend tests, ESLint, `tsc --noEmit`, and production build pass.
- [ ] Disposable migration chain and backup/restore integrity pass.
- [ ] Dependency audits are reviewed; suppressions have owner and expiry.
- [ ] Docker/Compose/Nginx runtime checklist passes on the target-like host.

## After start

- [ ] Migrations are at the approved single head.
- [ ] PostgreSQL and Redis healthy; ARQ heartbeat present.
- [ ] `/health/live` and `/health/ready` return 200.
- [ ] Frontend and BFF authentication work with secure cookies.
- [ ] Authenticated WebSocket connects through Nginx and reconnects safely.
- [ ] Metrics are private/authenticated and logs contain no secrets.
- [ ] Rollback owner and decision window are active.
