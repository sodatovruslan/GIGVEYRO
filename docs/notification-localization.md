# Notification localization contract

Notifications are stored as locale-neutral events. New producers call
`emit_semantic_notification` with a stable `NotificationMessageKey` and a small typed
`message_params` object. The Web cabinet renders the key through next-intl using its current
locale; Telegram renders the same key using the linked `TelegramConnection.language`.

## Key and parameter rules

- Name keys as `<domain>.<event>` and reuse the existing notification taxonomy.
- Add the key to the backend enum/catalog and the frontend key list plus all RU, EN and TG
  catalogs in the same change.
- Parameters may contain safe short references, Decimal amounts serialized as strings,
  currencies, statuses, counts and other non-secret scalar values.
- Never include credentials, authentication/session/link tokens, TOTP or recovery secrets,
  Telegram IDs, full payout destinations or private wallet addresses.
- Floats and complex/nested values are rejected. This prevents financial precision loss and
  keeps future channel rendering deterministic.

The translation coverage tests fail when any production key lacks a title or body in one of
the three supported languages.

## Compatibility and delivery

Rows created before migration 0028 keep their stored `title` and `message`. If `message_key` is
absent or unknown, Web uses those legacy fields. Telegram keeps its established generic legacy
presentation so arbitrary historical text is not forwarded to another channel.

Deep-link routing continues to use `Notification.type` and safe payload identifiers; localized
text is never used for navigation or business decisions. Realtime events remain invalidation
signals and trigger authoritative REST refetches. Delivery retries and OWNER delivery operations
continue to reference the canonical notification and outbox records.

## Adding a notification

1. Add one stable key to `NotificationMessageKey`.
2. Add matching RU, EN and TG title/body templates to the backend shared channel catalog.
3. Add the same nested key and translations to the frontend catalogs and key list.
4. Emit it from the business service with safe typed parameters and the existing deep-link
   payload/dedupe key.
5. Add producer, renderer and translation-coverage tests.

This contract is channel-neutral so a future email or SMS renderer can consume the same event
without changing business services.
