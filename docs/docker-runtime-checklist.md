# Docker runtime checklist (required later)

This checklist cannot be signed off without Docker. Use a separate Compose project name and disposable volumes; never attach the shared development database.

- [ ] Record Docker and Compose versions and healthy daemon information.
- [ ] Compose config resolves with a dedicated production-like env and no secrets printed.
- [ ] Build all images and inspect non-root users and healthchecks.
- [ ] PostgreSQL and Redis become healthy; Redis persistence and `noeviction` are effective.
- [ ] One-shot migrations reach `0027`; backend and worker start afterward.
- [ ] `/health/live` and `/health/ready` return 200 through Nginx.
- [ ] Frontend, login, and same-origin `/api/*` BFF routing work.
- [ ] Nginx config validation passes; only Nginx is published.
- [ ] Authenticated `/api/v1/ws` Upgrade works through Nginx; cross-process Redis broker delivery succeeds.
- [ ] ARQ heartbeat, metrics protection, rate limiting, and redacted JSON logs work.
- [ ] Backend/frontend restart recovery and graceful worker shutdown pass.
- [ ] TLS config passes on a staging hostname; enable HSTS only after HTTPS verification.
- [ ] Shutdown removes only resources created by the disposable project.
