import { apiFetch } from "@/lib/api/client";
import type { AuditLogEntry, IntegrationDiagnostics, MerchantWithdrawal, Paginated } from "@/lib/api/types";

export const auditActions = ["account.create", "account.update", "account.block", "account.unblock", "account.reset_password", "wallet.allocate", "wallet.adjust_insurance", "wallet.manual_adjust", "deal.complete", "deal.release", "appeal.review", "appeal.resolve", "withdrawal.approve", "withdrawal.reject", "withdrawal.mark_paid"] as const;
export const auditEntityTypes = ["account", "wallet", "deal", "appeal", "withdrawal"] as const;

interface AuditFilters {
  actorAccountId?: string;
  action?: string;
  entityType?: string;
  offset?: number;
}

function queryString(values: Record<string, string | number | undefined>) {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== "") params.set(key, String(value));
  });
  return params.toString();
}

export const ownerOperationsApi = {
  integrations: () => apiFetch<IntegrationDiagnostics>("/api/v1/owner/integrations/diagnostics"),
  auditLogs: (filters: AuditFilters = {}) => apiFetch<Paginated<AuditLogEntry>>(`/api/v1/owner/audit-logs?${queryString({
    actor_account_id: filters.actorAccountId,
    action: filters.action,
    entity_type: filters.entityType,
    limit: 50,
    offset: filters.offset ?? 0,
  })}`),
  withdrawals: (status?: MerchantWithdrawal["status"]) => apiFetch<Paginated<MerchantWithdrawal>>(`/owner/withdrawals?${queryString({ status, limit: 100, offset: 0 })}`),
  approveWithdrawal: (id: string, comment: string | null) => apiFetch<MerchantWithdrawal>(`/owner/withdrawals/${id}/approve`, { method: "POST", body: { comment } }),
  rejectWithdrawal: (id: string, comment: string | null) => apiFetch<MerchantWithdrawal>(`/owner/withdrawals/${id}/reject`, { method: "POST", body: { comment } }),
  markWithdrawalPaid: (id: string, comment: string | null) => apiFetch<MerchantWithdrawal>(`/owner/withdrawals/${id}/mark-paid`, { method: "POST", body: { comment } }),
};
