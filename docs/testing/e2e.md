# Browser E2E testing

## Architecture

The Playwright suite exercises the real local request path:

`Chromium -> Next.js UI/BFF -> FastAPI -> disposable PostgreSQL + namespaced Redis`

REST responses remain authoritative. The realtime scenario opens an authenticated WebSocket, receives a Redis-brokered invalidation event, and verifies that the UI performs a targeted REST refetch. No external blockchain, exchange, Telegram, or real-money service is called.

## Prerequisites

- Python 3.11 and the dependencies from `GIGVEYRO_Backend/requirements.txt`.
- Node.js 20+ and `npm ci` in `gigveyro-frontend`.
- A local PostgreSQL server. `DATABASE_URL` must identify a database whose user may create and drop databases.
- A local Redis server reachable through `REDIS_URL`.
- Chromium installed with `npx playwright install chromium`. On Windows, the harness can use the system Google Chrome executable when present.

The harness reads connection coordinates from the process environment first and the backend `.env` only as a local fallback. It never changes `.env`.

## Disposable isolation

Each invocation derives a unique database name ending in `_e2e_<pid>_<random>`, creates it, migrates it to the current Alembic head, and seeds deterministic test-only records. It uses a unique Redis key prefix for realtime, rate limiting, and ARQ. In `finally`, it stops all child processes, deletes only keys under that prefix, and drops only the generated database.

The shared development database is never migrated or mutated. Safety flags are forced for the child processes:

- `PAYOUT_ENABLED=false`
- `PAYOUT_PROVIDER_MODE=disabled`
- `PAYOUT_SIMULATION_ENABLED=false`
- `BYBIT_WRITE_ENABLED=false`
- mock deposit provider and fallback exchange-rate provider
- Telegram bot and delivery disabled

## Commands

From `gigveyro-frontend`:

```text
npm run test:e2e
npm run test:e2e:headed
npm run test:e2e:ui
```

The standard `npm test` command remains a browser-free Vitest run. The E2E wrapper starts FastAPI, the ARQ worker, and Next.js development mode with its documented Webpack option, waits for readiness, runs Playwright, and always performs cleanup. Webpack is selected deliberately because the Next.js 16 Turbopack development route compiler can transiently return 404 for BFF handlers while compiling a preceding unknown route; this suite must not confuse that compiler race with product behavior.

## Personas

The seed creates an OWNER, two USER accounts, two MERCHANT accounts, and a blocked USER. Credentials and the OWNER TOTP seed are deterministic, test-only values supplied only to disposable processes. Real credentials and private integration secrets are neither required nor written to artifacts.

## Covered journeys

- Closed public registration, localized managed-onboarding text, and the GigaPay brand.
- OWNER invalid login, deterministic TOTP login, session persistence, logout, account provisioning, validation/conflict behavior, and critical route smoke.
- USER and MERCHANT login/logout, dashboards, settings/security, role routes, and forbidden OWNER navigation.
- Two concurrent USER sessions, logout-all-other-sessions, password rotation, TOTP setup, recovery-code login, and blocked-account denial.
- RU/EN/TG and Light/Dark/System preference smoke.
- Synthetic deposit creation and credit, visible balance and semantic notification, and replay without duplicate credit.
- OWNER exact-match reconciliation plus reprocess/ignore with no credit on ignore.
- MERCHANT withdrawal creation in pending state, OWNER visibility, cross-merchant isolation, and disabled live payout controls.
- RedisRealtimeBroker WebSocket invalidation followed by authoritative OWNER deal-list refetch.
- Health, 401/403/409/422 handling, unknown routes, accessible control names, labeled forms, modal confirmation, and duplicate-ID smoke.
- OWNER treasury/risk/fees/payout pages render without exposing integration secrets.

Failure screenshots, video, traces, and reports are written under ignored Playwright artifact directories. CI uploads `test-results` only when the E2E job fails and retains it for seven days.

## CI

The `Browser E2E (Chromium)` job provisions dedicated PostgreSQL and Redis service containers, installs backend/frontend dependencies and Chromium, then invokes the same `npm run test:e2e` harness. The database created by the harness is disposable even inside the already isolated CI PostgreSQL service.

## Intentional exclusions

The suite does not send Tron transactions, sign wallets, call Binance/Bybit write APIs, send Telegram messages, approve or execute real withdrawals, or enable a payout provider. Nginx Upgrade routing and the complete Docker Compose runtime remain part of the later Docker/Nginx runtime validation stage.

REAL-MONEY OPERATIONS: NONE.
