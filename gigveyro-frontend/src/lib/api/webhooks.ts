import { apiFetch } from "@/lib/api/client";
import type { Paginated, Webhook, WebhookCreated, WebhookDelivery, WebhookStatus } from "@/lib/api/types";

export const webhooksApi = {
  list: (limit = 20, offset = 0) => apiFetch<Paginated<Webhook>>(`/merchant/webhooks?${new URLSearchParams({ limit: String(limit), offset: String(offset) })}`),
  get: (id: string) => apiFetch<Webhook>(`/merchant/webhooks/${id}`),
  create: (url: string, eventTypes: string[]) => apiFetch<WebhookCreated>("/merchant/webhooks", { method: "POST", body: { url, event_types: eventTypes } }),
  update: (id: string, input: { url?: string; status?: WebhookStatus; event_types?: string[] }) => apiFetch<Webhook>(`/merchant/webhooks/${id}`, { method: "PATCH", body: input }),
  deliveries: (id: string, limit = 20, offset = 0) => apiFetch<Paginated<WebhookDelivery>>(`/merchant/webhooks/${id}/deliveries?${new URLSearchParams({ limit: String(limit), offset: String(offset) })}`),
};
