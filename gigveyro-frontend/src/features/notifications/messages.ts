import { useTranslations } from "next-intl";

import type { NotificationItem } from "@/lib/api/types";

export const notificationMessageKeys = [
  "appeal.opened",
  "appeal.resolved",
  "deposit.credited",
  "withdrawal.cancelled",
  "withdrawal.approved",
  "withdrawal.rejected",
  "withdrawal.completed",
  "fiat.balance_updated",
  "security.recovery_used",
  "security.2fa_enabled",
  "security.2fa_disabled",
  "security.recovery_regenerated",
  "security.password_changed",
  "security.logout_all",
  "security.session_revoked",
  "payout.approval_required",
  "payout.execution_failed",
  "payout.reconciliation_required",
  "treasury.warning",
  "treasury.critical",
  "treasury.stale",
] as const;

export type NotificationMessageKey = (typeof notificationMessageKeys)[number];

const knownKeys = new Set<string>(notificationMessageKeys);

type Translate = (
  key: string,
  values?: Record<string, string | number | Date>,
) => string;

export function renderNotificationMessage(
  item: Pick<NotificationItem, "title" | "message" | "message_key" | "message_params">,
  translate: Translate,
): { title: string; message: string } {
  if (!item.message_key || !knownKeys.has(item.message_key)) {
    return { title: item.title, message: item.message };
  }
  const values: Record<string, string | number | Date> = {};
  for (const [key, value] of Object.entries(item.message_params ?? {})) {
    if (value !== null && typeof value !== "boolean") values[key] = value;
    else if (value !== null) values[key] = String(value);
  }
  try {
    return {
      title: translate(`${item.message_key}.title`, values),
      message: translate(`${item.message_key}.body`, values),
    };
  } catch {
    return { title: item.title, message: item.message };
  }
}

export function useNotificationMessage() {
  const translate = useTranslations("notificationMessages") as unknown as Translate;
  return (item: NotificationItem) => renderNotificationMessage(item, translate);
}
