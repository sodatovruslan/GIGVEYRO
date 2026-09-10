import { apiFetch } from "@/lib/api/client";
import type { ApiKey, Paginated } from "@/lib/api/types";

export const ownerApiKeysApi = {
  list: (limit = 20, offset = 0) => apiFetch<Paginated<ApiKey>>(`/owner/api-keys?${new URLSearchParams({ limit: String(limit), offset: String(offset) })}`),
  revoke: (id: string) => apiFetch<ApiKey>(`/owner/api-keys/${id}/revoke`, { method: "POST" }),
};
