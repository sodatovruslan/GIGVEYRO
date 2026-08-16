# GIGVEYRO Backend — Security Documentation & Audit Policy

## 1. Secrets & Credentials Management
- Hardcoded secrets in production are strictly forbidden.
- `JWT_SECRET_KEY` must be configured via environment variables and possess a minimum length of 32 characters in production (`APP_ENV=production`).
- Database credentials must be provided via `DATABASE_URL`.

## 2. Payout Safety Configuration
- `PAYOUT_ENABLED` defaults to `False` in all environments.
- Private keys, mnemonics, or automated wallet signing code are strictly absent from the application codebase.
- Payout execution passes through explicit provider abstractions (`MockPayoutProvider` or `ExternalPayoutAdapter`) with safety checks.

## 3. Card Data Protection
- Payment card numbers are masked at the schema/API boundary.
- Plaintext full card numbers are never returned in public or owner endpoints.
- Known limitation: Database contains canonical digits for requisite uniqueness matching; encryption-at-rest is recommended for production database storage.

## 4. Middleware & Headers
- `SecurityHeadersMiddleware`: Sets `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, and `Referrer-Policy`.
- `RequestIDMiddleware`: Generates or propagates `X-Request-ID` for end-to-end request tracing.
- `RateLimitMiddleware`: Protects sensitive routes like `/auth/login` against brute-force attempts.
