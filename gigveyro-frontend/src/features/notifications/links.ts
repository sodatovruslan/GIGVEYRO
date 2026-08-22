import type { NotificationItem, UserRole } from "@/lib/api/types";

/** Only links to routes that actually exist for the given role, built from
 * payload fields the backend actually sends - never guessed. */
export function notificationLink(item: NotificationItem, role: UserRole): string | null {
  const payload = item.payload as Record<string, unknown> | null;
  if (!payload) return null;
  if ((item.type === "APPEAL_OPENED" || item.type === "APPEAL_RESOLVED") && payload.appeal_id) {
    return `/${role}/appeals`;
  }
  if (item.type === "DEPOSIT_CONFIRMED" && payload.deposit_id && role !== "merchant") {
    return `/${role}/deposits`;
  }
  if (item.type === "WITHDRAWAL_STATUS_CHANGED" && payload.withdrawal_id && role !== "user") {
    return `/${role}/withdrawals`;
  }
  return null;
}
