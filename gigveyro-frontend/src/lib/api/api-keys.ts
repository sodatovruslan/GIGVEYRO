import { apiFetch } from "@/lib/api/client";
import type { ApiKey, ApiKeyCreated, Paginated } from "@/lib/api/types";

export const apiKeysApi = {
  list: (limit = 20, offset = 0) => apiFetch<Paginated<ApiKey>>(`/merchant/api-keys?${new URLSearchParams({ limit: String(limit), offset: String(offset) })}`),
  create: (label: string) => apiFetch<ApiKeyCreated>("/merchant/api-keys", { method: "POST", body: { label } }),
  revoke: (id: string) => apiFetch<ApiKey>(`/merchant/api-keys/${id}/revoke`, { method: "POST" }),
};
