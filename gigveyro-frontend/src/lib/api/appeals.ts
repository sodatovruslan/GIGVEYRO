import { apiFetch } from "@/lib/api/client";
import type { Appeal, AppealReason, Paginated } from "@/lib/api/types";

export const appealsApi = {
  list: (owner: boolean, limit = 20, offset = 0) => apiFetch<Paginated<Appeal>>(`${owner ? "/owner" : ""}/appeals?limit=${limit}&offset=${offset}`),
  open: (dealId: string, reasonCode: AppealReason, message: string) => apiFetch<Appeal>(`/appeals/deals/${dealId}/appeal`, { method: "POST", body: { reason_code: reasonCode, message } }),
  cancel: (id: string) => apiFetch<Appeal>(`/appeals/${id}/cancel`, { method: "POST" }),
  review: (id: string, note: string) => apiFetch<Appeal>(`/owner/appeals/${id}/review`, { method: "POST", body: { note: note || null } }),
  resolve: (id: string, resolution: "settle_to_merchant" | "release_to_user", ownerNote: string) => apiFetch<Appeal>(`/owner/appeals/${id}/resolve`, { method: "POST", body: { resolution, owner_note: ownerNote } }),
};
