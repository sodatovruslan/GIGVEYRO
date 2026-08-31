import { apiFetch } from "@/lib/api/client";
import type {
  NotificationItem,
  NotificationPreferences,
  TelegramConnection,
  TelegramLinkToken,
} from "@/lib/api/types";

export const notificationsApi = {
  list: (limit = 20, offset = 0) => apiFetch<NotificationItem[]>(`/notifications?limit=${limit}&offset=${offset}`),
  unreadCount: () => apiFetch<{ unread_count: number }>("/notifications/unread-count"),
  markRead: (id: string) => apiFetch<void>(`/notifications/${id}/read`, { method: "POST" }),
  markAllRead: () => apiFetch<{ updated_count: number }>("/notifications/read-all", { method: "POST" }),
  preferences: () => apiFetch<NotificationPreferences>("/notifications/preferences"),
  updatePreferences: (input: Partial<NotificationPreferences>) => apiFetch<NotificationPreferences>("/notifications/preferences", { method: "PATCH", body: input }),
  telegramConnection: () => apiFetch<TelegramConnection>("/telegram/connection"),
  telegramLink: () => apiFetch<TelegramLinkToken>("/telegram/link-token", { method: "POST" }),
  updateTelegram: (input: Partial<Pick<TelegramConnection, "language" | "delivery_enabled">>) =>
    apiFetch<TelegramConnection>("/telegram/connection", { method: "PATCH", body: input }),
  disconnectTelegram: () => apiFetch<void>("/telegram/connection", { method: "DELETE" }),
};
