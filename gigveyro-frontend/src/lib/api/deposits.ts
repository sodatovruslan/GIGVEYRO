import { apiFetch } from "@/lib/api/client";
import type { Deposit, DepositStatus, Paginated, UnmatchedTransfer } from "@/lib/api/types";

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
  list: (owner: boolean, status?: DepositStatus, filters: DepositOwnerFilters = {}, limit = 20, offset = 0) => apiFetch<Paginated<Deposit>>(`${owner ? "/owner" : ""}/deposits?${queryString({
    status,
    limit,
    offset,
    ...(owner ? { search: filters.search, tx_hash: filters.txHash, date_from: filters.dateFrom, date_to: filters.dateTo } : {}),
  })}`),
  get: (owner: boolean, id: string) => apiFetch<Deposit>(`${owner ? "/owner" : ""}/deposits/${id}`),
  create: (amount: string) => apiFetch<Deposit>("/deposits", { method: "POST", body: { amount } }),
};

export interface UnmatchedTransferFilters {
  status?: "MATCHED" | "AMBIGUOUS" | "UNMATCHED";
  txHash?: string;
  dateFrom?: string;
  dateTo?: string;
  minAmount?: string;
  maxAmount?: string;
}

export const unmatchedTransfersApi = {
  list: (filters: UnmatchedTransferFilters = {}, limit = 20, offset = 0) => apiFetch<Paginated<UnmatchedTransfer>>(`/owner/deposits/unmatched?${queryString({
    status: filters.status,
    tx_hash: filters.txHash,
    date_from: filters.dateFrom,
    date_to: filters.dateTo,
    min_amount: filters.minAmount,
    max_amount: filters.maxAmount,
    limit,
    offset,
  })}`),
  get: (id: string) => apiFetch<UnmatchedTransfer>(`/owner/deposits/unmatched/${id}`),
};
