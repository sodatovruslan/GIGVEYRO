import { apiFetch } from "@/lib/api/client";
import type { Deposit, DepositStatus, Paginated } from "@/lib/api/types";

export interface DepositOwnerFilters {
  search?: string;
  txHash?: string;
  dateFrom?: string;
  dateTo?: string;
}

function queryString(values: Record<string, string | number | undefined>) {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== "") params.set(key, String(value));
  });
  return params.toString();
}

export const depositsApi = {
  list: (owner: boolean, status?: DepositStatus, filters: DepositOwnerFilters = {}) => apiFetch<Paginated<Deposit>>(`${owner ? "/owner" : ""}/deposits?${queryString({
    status,
    limit: 100,
    offset: 0,
    ...(owner ? { search: filters.search, tx_hash: filters.txHash, date_from: filters.dateFrom, date_to: filters.dateTo } : {}),
  })}`),
  get: (owner: boolean, id: string) => apiFetch<Deposit>(`${owner ? "/owner" : ""}/deposits/${id}`),
  create: (amount: string) => apiFetch<Deposit>("/deposits", { method: "POST", body: { amount } }),
};
