# Telegram Bot integration

Telegram is an optional GIGVEYRO notification and read-only account interface. It reuses the
existing accounts, RBAC, notifications, delivery outbox, audit, Redis rate limiting and ARQ
worker. It is not an authentication factor and cannot perform financial mutations.

## Create and configure the bot

1. Open the verified `@BotFather` account in Telegram and create a bot with `/newbot`.
2. Keep the token outside source control. Put it only in the local/deployment environment as
   `TELEGRAM_BOT_TOKEN`; never paste it into frontend variables, logs, documentation or issues.
3. Set `TELEGRAM_BOT_USERNAME` without relying on it for user identity.
4. Enable the bot and delivery explicitly. Both default to off.

Development example (replace placeholders only in an untracked local `.env`):

```dotenv
TELEGRAM_BOT_ENABLED=true
TELEGRAM_BOT_TOKEN=<botfather-token>
TELEGRAM_BOT_USERNAME=<bot-username>
TELEGRAM_DELIVERY_ENABLED=true
TELEGRAM_BOT_MODE=polling
TELEGRAM_WEB_APP_URL=http://localhost:3000
```

Start polling as a separate process, never inside the FastAPI web-worker lifespan:

```console
python -m app.telegram_bot
```

Only one polling process may consume updates for a bot token.

## Account linking

An authenticated OWNER, USER or MERCHANT opens Notifications settings and chooses **Connect
Telegram**. The backend returns a 256-bit URL-safe token in a `t.me` deep link. Only its SHA-256
hash is stored. The token is tied to that account, expires after 5–10 minutes, is single-use and
atomically consumed by `/start <token>`. Creating another token revokes older unused tokens.

The immutable numeric Telegram user ID and private chat ID are authoritative. Username and first
name are display metadata only. A blocked GIGVEYRO account cannot link or use commands, and its
notification delivery stops. Disconnecting preserves notification and audit history.

## Supported commands

All commands are rate-limited and re-check the current account and role:

- Common: `/start`, `/help`, `/status`, `/notifications`, `/settings`, `/language`, `/unlink`.
- OWNER: `/risk`, `/treasury`, `/payouts`, `/withdrawals`, `/deals`.
- MERCHANT: `/balance`, `/deals`, `/withdrawals`.
- USER: `/balance`, `/deals`.

The bot exposes only role-scoped summaries. OWNER treasury commands show risk status, not exact
external exchange balances. Telegram does not replace TOTP, login, sessions or web authorization.

There are deliberately no Telegram commands or buttons for payout approval/execution, withdrawal
creation/approval, transfers, balance allocation, deal settlement, fiat conversion, fee/risk
policy changes, payout destinations, or Binance/Bybit writes. All financial actions stay in the
authenticated web UI.

## Notification delivery

Business services persist the existing canonical `Notification` and, when Telegram delivery is
enabled, a notification outbox row in the same database transaction. The ARQ worker sends later
through the aiogram adapter. Telegram downtime therefore cannot roll back a deal, withdrawal,
balance, fee, conversion or payout-state transaction.

Delivery is unique per canonical notification/channel. Network failures and Telegram 5xx errors
use bounded exponential retry; HTTP 429 honors `retry_after`. Blocked/chat-missing and invalid
credential/config errors are terminal. A blocked bot connection is marked delivery-disabled and
can be inspected from web settings. Messages use localized safe summaries and ordinary web routes;
no authentication/session/link tokens are placed in notification URLs.

Telegram's Bot API does not provide an idempotency key for `sendMessage`. Database uniqueness
prevents normal duplicate scheduling and retries after recorded success. An unavoidable residual
risk remains if Telegram accepts a message but the network fails before the worker receives the
response or commits the result.

## Production webhook runbook (future Docker/Nginx stage)

Production configuration is fail-closed and requires:

- an HTTPS public base URL;
- `TELEGRAM_BOT_MODE=webhook`;
- a random `TELEGRAM_WEBHOOK_SECRET` of at least 32 URL-safe characters;
- an Nginx route that preserves `X-Telegram-Bot-Api-Secret-Token` to the backend;
- Telegram `setWebhook` configured with that secret and the exact backend webhook URL;
- exactly one logical webhook consumer for each update;
- proxy/body/time limits suitable for small Telegram JSON updates.

Before enabling delivery, validate `getMe`, webhook secret rejection, private-chat handling,
link/unlink, one safe notification, diagnostics and worker retries. Roll back with Telegram
`deleteWebhook`, set `TELEGRAM_BOT_ENABLED=false` and `TELEGRAM_DELIVERY_ENABLED=false`, then stop
the consumer. Never expose the webhook secret in an Nginx access log.

Webhook HTTPS/Nginx runtime has intentionally not been validated until Docker is available.
