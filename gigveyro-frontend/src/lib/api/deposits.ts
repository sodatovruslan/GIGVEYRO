import { apiFetch } from "@/lib/api/client";
import type { Deposit, DepositReconciliationResult, DepositStatus, Paginated, ReconciliationStatus, UnmatchedTransfer, UnmatchedTransferDetail } from "@/lib/api/types";

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
  reconciliationStatus?: ReconciliationStatus;
  txHash?: string;
  reason?: string;
  dateFrom?: string;
  dateTo?: string;
  minAmount?: string;
  maxAmount?: string;
}

export const unmatchedTransfersApi = {
  list: (filters: UnmatchedTransferFilters = {}, limit = 20, offset = 0) => apiFetch<Paginated<UnmatchedTransfer>>(`/owner/deposits/unmatched?${queryString({
    status: filters.status,
    reconciliation_status: filters.reconciliationStatus,
    tx_hash: filters.txHash,
    reason: filters.reason,
    date_from: filters.dateFrom,
    date_to: filters.dateTo,
    min_amount: filters.minAmount,
    max_amount: filters.maxAmount,
    limit,
    offset,
  })}`),
  get: (id: string) => apiFetch<UnmatchedTransferDetail>(`/owner/deposits/unmatched/${id}`),
  link: (id: string, depositId: string, idempotencyKey: string) => apiFetch<DepositReconciliationResult>(`/owner/deposits/unmatched/${id}/link`, { method: "POST", body: { deposit_id: depositId, idempotency_key: idempotencyKey } }),
  reprocess: (id: string, idempotencyKey: string) => apiFetch<DepositReconciliationResult>(`/owner/deposits/unmatched/${id}/reprocess`, { method: "POST", body: { idempotency_key: idempotencyKey } }),
  ignore: (id: string, reason: string, idempotencyKey: string) => apiFetch<DepositReconciliationResult>(`/owner/deposits/unmatched/${id}/ignore`, { method: "POST", body: { reason, idempotency_key: idempotencyKey } }),
};
