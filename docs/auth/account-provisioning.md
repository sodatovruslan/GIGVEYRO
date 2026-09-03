# Account provisioning and onboarding (V1)

## Policy

GigaPay V1 is a closed, owner-provisioned platform. Public self-registration is disabled by design: the API has no `/register`, `/public/register`, or `/auth/register` route, and the login page has no signup form or signup call to action.

Only an authenticated `OWNER` can create managed accounts through `POST /owner/accounts`. The endpoint accepts the `USER` and `MERCHANT` roles only. A `USER` or `MERCHANT` cannot create another account, and this restriction is enforced by backend RBAC rather than by the frontend alone. Owner account bootstrap is a separate operational procedure and is not exposed through this endpoint.

## Security rationale

Controlled onboarding reduces automated abuse and fraud exposure, makes the intended `USER` and `MERCHANT` assignment explicit, and prevents uncontrolled account creation while GigaPay's compliance and identity-verification processes evolve. This is a product and security boundary for V1, not a legal or regulatory assurance.

## Provisioning flow

1. The owner opens **OWNER → Accounts → Create account**.
2. The owner selects `USER` or `MERCHANT` and enters the username, full name, optional email and phone, and an initial password.
3. Backend V1 validates uniqueness, hashes the password immediately, creates an active account, and provisions the role-specific wallet/settings required by the existing business model.
4. The UI shows the new account reference, username, role, active status, and role-specific onboarding guidance. It never displays the initial password again.
5. The owner gives the username and initial password to the intended person through an organization-approved secure channel.
6. The account holder signs in and changes the initial password under **Settings → Security**. They may link Telegram from Settings after authentication.

The current schema does not have a `must_change_password` flag. Password change on first login is therefore an onboarding instruction, not a backend-enforced transition. Adding an enforced first-login change later would require an explicit product/security design and likely a migration.

## Password handling and recovery

- The account table stores `password_hash` only. Plaintext passwords are neither persisted nor returned by account APIs.
- The creation response cannot recover or redisplay the initial password. If handoff fails, the owner must set a new one with `POST /owner/accounts/{account_id}/reset-password`.
- An authenticated `USER` or `MERCHANT` can change their own password through `POST /auth/password/change`.
- An owner reset revokes the target account's active sessions. The new password must again be handed over through an approved secure channel.
- V1 has no public “forgot password”, email reset, SMS reset, or anonymous recovery flow. A user who cannot sign in must contact the GigaPay administrator.

## Activation and blocking

New managed accounts are active on creation. An owner may block an account through `POST /owner/accounts/{account_id}/block` and restore it through the corresponding `/unblock` endpoint.

A blocked account cannot sign in, refresh a session, or use a previously issued access token against protected endpoints. Blocking also revokes its sessions; role-specific safeguards such as disabling user traffic remain backend-controlled.

## Telegram semantics

Telegram is an optional notification and read-only command channel linked to an existing authenticated account. It is not a registration mechanism, identity proof for creating an account, or a replacement for GigaPay credentials. Linking uses a one-time deep link created from the web cabinet; inactive accounts cannot consume a link token. Unlinking Telegram does not delete or deactivate the GigaPay account.

## OpenAPI and client contract

The OpenAPI schema intentionally lists the owner-managed account endpoints and has no public registration operation. Clients must not infer account creation from login, Telegram, email, or phone flows. The backend remains the authority for RBAC, account status, password validation, wallet provisioning, and session revocation.

## Future public registration prerequisites

Public registration must not be enabled by adding a form alone. A future version would require a separately approved threat model and product flow covering identity verification, abuse and bot controls, rate limits, contact verification, role eligibility, duplicate/fraud detection, password policy, consent and legal records, activation states, recovery, observability, support procedures, and safe migration from owner-provisioned accounts.
