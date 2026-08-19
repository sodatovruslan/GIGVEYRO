import { apiFetch } from "@/lib/api/client";
import type { NotificationItem, NotificationPreferences, TelegramLinkCode } from "@/lib/api/types";

export const notificationsApi = {
  list: () => apiFetch<NotificationItem[]>("/notifications?limit=100&offset=0"),
  unreadCount: () => apiFetch<{ unread_count: number }>("/notifications/unread-count"),
  markRead: (id: string) => apiFetch<void>(`/notifications/${id}/read`, { method: "POST" }),
  markAllRead: () => apiFetch<{ updated_count: number }>("/notifications/read-all", { method: "POST" }),
  preferences: () => apiFetch<NotificationPreferences>("/notifications/preferences"),
  updatePreferences: (input: Partial<NotificationPreferences>) => apiFetch<NotificationPreferences>("/notifications/preferences", { method: "PATCH", body: input }),
  telegramCode: () => apiFetch<TelegramLinkCode>("/telegram/link-code", { method: "POST" }),
};
