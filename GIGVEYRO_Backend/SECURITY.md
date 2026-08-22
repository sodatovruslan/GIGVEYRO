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
- Known limitation: `in_memory_rate_limiter` (`app/core/middleware.py`) keys on `request.client.host`, which is the proxy's address (not the real client) behind a reverse proxy unless `X-Forwarded-For` handling is added, and its counters are per-process — not shared across multiple workers. `REDIS_URL` is already configured (see infra settings) so the migration path is a Redis-backed sliding-window limiter using the same `is_rate_limited(key, max_requests, window_seconds)` interface; not implemented here as it is outside this stage's scope.

## 5. Authentication Sessions (V1.1)
- **Password hashing**: Argon2id via `pwdlib.PasswordHash.recommended()`. Login is constant-time regardless of whether the username exists (dummy-hash verify), so timing can't be used to enumerate accounts. Login/reset error messages never distinguish "unknown user" from "wrong password".
- **Access tokens**: JWT, HS256, `ACCESS_TOKEN_EXPIRE_MINUTES` (default 15 min), claims `sub`/`role`/`type`/`session_id`/`jti`/`exp`. `role` is never trusted from the token alone — every protected endpoint re-reads the account (and its `is_active` flag) from the database, and `require_roles` checks the DB-loaded role.
- **Refresh tokens & server-side sessions**: Every login creates an `AuthSession` row (`app/models/auth_session.py`). Only a SHA-256 hash of the refresh token is stored — never the plaintext token. `POST /auth/refresh` rotates the token in place on the same session row: the old token's hash is replaced, `rotation_counter` increments, and `last_used_at` updates. The session row lock (`SELECT ... FOR UPDATE`) makes concurrent refresh attempts on the same token serialize correctly — exactly one wins.
- **Reuse detection**: If a refresh token is presented whose hash no longer matches the session's current `refresh_token_hash` (i.e. it was already rotated away), the entire session is immediately revoked (`revoked_reason="reuse_detected"`) and the request is rejected with `409 Conflict`. This is intentionally strict — even two legitimate concurrent refreshes from the same client (e.g. two open tabs racing) will trip this and force re-login, since the system cannot distinguish that from an attacker replaying a stolen token. There is no grace-period exception in V1.1.
- **Immediate revocation on access tokens**: access tokens also carry `session_id`. `get_current_account` checks the session's `revoked_at`/`expires_at` on every request, so a revoked session (logout, logout-all, password reset, block) is rejected immediately rather than staying valid until the access token's natural 15-minute expiry. (Tokens minted without a `session_id`, e.g. bootstrap scripts, fall back to the pre-V1.1 account-only check.)
- **Logout**: `POST /auth/logout` revokes the session behind the given refresh token. Idempotent — an already-invalid or already-revoked token is treated as "nothing to do", never an error, so the response never discloses whether the token was valid.
- **Logout all devices**: `POST /auth/logout-all` (authenticated) revokes every active session for the caller's own account.
- **Session self-service**: `GET /auth/sessions` lists the caller's own active sessions (id, created/last-used/expires timestamps, a coarse device label, `is_current`) — never the token or its hash. `DELETE /auth/sessions/{id}` revokes one of the caller's own sessions; attempting to revoke another account's session returns `404` (not `403`, to avoid confirming the session id belongs to someone).
- **Password reset**: `AccountService.reset_password` (OWNER-only, `POST /owner/accounts/{id}/reset-password`) revokes every active session of the target account in the same call, so a compromised account can't stay logged in through the old password.
- **Block**: `AccountService.set_account_active(is_active=False)` also revokes every active session of the blocked account (in addition to the pre-existing `is_active` check that already rejects login/refresh/protected requests). Unblocking does **not** restore the revoked sessions — the user must log in again.
- **Session cleanup**: `AuthService.cleanup_expired_sessions()` deletes sessions expired more than `SESSION_CLEANUP_RETENTION_DAYS` (default 30) days ago. Not scheduled automatically — a production worker/cron must call it periodically.
- **Audit**: `auth.login`, `auth.logout`, `auth.logout_all`, and `auth.session_revoked` (reuse detection or explicit user revoke) are recorded via the existing `AuditService`/`AuditLog`. Passwords, tokens, and refresh-token hashes are never written to audit metadata.
- **CSRF**: The frontend BFF is cookie-based (`HttpOnly`, `SameSite=Lax`, `Secure` in production) and checks the `Origin` header on mutation routes when present. This is accepted as the V1.1 baseline; no separate CSRF token scheme was added, since `SameSite=Lax` already blocks cross-site form/script-initiated state-changing requests in modern browsers. If a future browser-compat reason requires it, the double-submit token pattern is the intended upgrade path.
- **2FA**: Not implemented in V1.1. OWNER accounts have no two-factor requirement yet — deferred to a follow-up stage after this session/rotation baseline is verified stable, per the project's staged-rollout policy.
