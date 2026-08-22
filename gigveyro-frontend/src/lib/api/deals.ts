import { apiFetch } from "@/lib/api/client";
import type { Deal, Paginated } from "@/lib/api/types";

export const dealsApi = {
  merchantList: () => apiFetch<Paginated<Deal>>("/merchant/deals?limit=100&offset=0"),
  merchantCreate: (amountTjs: string) => apiFetch<Deal>("/merchant/deals", { method: "POST", body: { amount_tjs: amountTjs } }),
  userList: () => apiFetch<Paginated<Deal>>("/deals?limit=100&offset=0"),
  available: () => apiFetch<Paginated<Deal>>("/deals/available?limit=100&offset=0"),
  accept: (id: string, requisiteId: string) => apiFetch<Deal>(`/deals/${id}/accept`, { method: "POST", body: { payment_requisite_id: requisiteId } }),
  ownerList: () => apiFetch<Paginated<Deal>>("/owner/deals?limit=100&offset=0"),
  ownerAction: (id: string, action: "complete" | "release") => apiFetch<Deal>(`/owner/deals/${id}/${action}`, { method: "POST" }),
  ownerGet: (id: string) => apiFetch<Deal>(`/owner/deals/${id}`),
  merchantGet: (id: string) => apiFetch<Deal>(`/merchant/deals/${id}`),
  userGet: (id: string) => apiFetch<Deal>(`/deals/${id}`),
};
