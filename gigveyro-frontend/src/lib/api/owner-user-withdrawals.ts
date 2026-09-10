import { apiFetch } from "@/lib/api/client";
import type { Paginated, UserWithdrawal } from "@/lib/api/types";

function queryString(values: Record<string, string | number | undefined>) {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== "") params.set(key, String(value));
  });
  return params.toString();
}

export const ownerUserWithdrawalsApi = {
  list: (status?: UserWithdrawal["status"], limit = 20, offset = 0) => apiFetch<Paginated<UserWithdrawal>>(`/owner/user-withdrawals?${queryString({ status, limit, offset })}`),
  get: (id: string) => apiFetch<UserWithdrawal>(`/owner/user-withdrawals/${id}`),
  approve: (id: string, comment: string | null) => apiFetch<UserWithdrawal>(`/owner/user-withdrawals/${id}/approve`, { method: "POST", body: { comment } }),
  reject: (id: string, comment: string | null) => apiFetch<UserWithdrawal>(`/owner/user-withdrawals/${id}/reject`, { method: "POST", body: { comment } }),
};
