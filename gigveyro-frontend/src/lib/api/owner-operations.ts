import { apiFetch } from "@/lib/api/client";
import type { AuditLogEntry, FeePolicy, FeePreview, FeeType, IntegrationDiagnostics, MerchantWithdrawal, Paginated, ProfitEntry, ProfitSummary, RiskPolicy, RiskPolicyInput, RiskPreview, TreasurySummary } from "@/lib/api/types";

export const auditActions = ["account.create", "account.update", "account.block", "account.unblock", "account.reset_password", "wallet.allocate", "wallet.adjust_insurance", "wallet.manual_adjust", "fiat.allocate", "fiat.convert", "fee_policy.created", "fee_policy.activated", "fee_policy.disabled", "risk_policy.created", "risk_policy.activated", "risk_policy.disabled", "deal.complete", "deal.release", "appeal.review", "appeal.resolve", "withdrawal.approve", "withdrawal.reject", "withdrawal.mark_paid"] as const;
export const auditEntityTypes = ["account", "wallet", "fiat_wallet", "fiat_conversion", "fee_policy", "fee_policy_component", "risk_policy", "deal", "appeal", "withdrawal"] as const;

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
  feePolicy: () => apiFetch<FeePolicy>("/api/v1/owner/fees/policy"),
  createFeePolicy: (components: Record<FeeType, { enabled: boolean; percent_bps: number; fixed_fee: string; min_fee: string | null; max_fee: string | null; payer: "USER" | "MERCHANT" | null }>) => apiFetch<FeePolicy>("/api/v1/owner/fees/policies", { method: "POST", body: { components } }),
  activateFeePolicy: (id: string) => apiFetch<FeePolicy>(`/api/v1/owner/fees/policies/${id}/activate`, { method: "POST" }),
  previewFee: (feeType: FeeType, currency: "TJS" | "RUB" | "USDT", amount: string, policyId?: string) => apiFetch<FeePreview>("/api/v1/owner/fees/preview", { method: "POST", body: { policy_id: policyId, fee_type: feeType, currency, amount } }),
  profitSummary: () => apiFetch<ProfitSummary>("/api/v1/owner/profit/summary"),
  profitEntries: (filters: { feeType?: FeeType; currency?: string; offset?: number } = {}) => apiFetch<Paginated<ProfitEntry>>(`/api/v1/owner/profit/entries?${queryString({ fee_type: filters.feeType, currency: filters.currency, limit: 20, offset: filters.offset ?? 0 })}`),
  treasurySummary: () => apiFetch<TreasurySummary>("/api/v1/owner/treasury/summary"),
  refreshTreasury: () => apiFetch<TreasurySummary>("/api/v1/owner/treasury/refresh", { method: "POST" }),
  riskPolicy: () => apiFetch<RiskPolicy>("/api/v1/owner/risk/policy"),
  previewRiskPolicy: (body: RiskPolicyInput) => apiFetch<RiskPreview>("/api/v1/owner/risk/preview", { method: "POST", body }),
  createRiskPolicy: (body: RiskPolicyInput) => apiFetch<RiskPolicy>("/api/v1/owner/risk/policies", { method: "POST", body }),
  activateRiskPolicy: (id: string) => apiFetch<RiskPolicy>(`/api/v1/owner/risk/policies/${id}/activate`, { method: "POST" }),
  auditLogs: (filters: AuditFilters = {}) => apiFetch<Paginated<AuditLogEntry>>(`/api/v1/owner/audit-logs?${queryString({
    actor_account_id: filters.actorAccountId,
    action: filters.action,
    entity_type: filters.entityType,
    limit: 50,
    offset: filters.offset ?? 0,
  })}`),
  withdrawals: (status?: MerchantWithdrawal["status"], limit = 20, offset = 0) => apiFetch<Paginated<MerchantWithdrawal>>(`/owner/withdrawals?${queryString({ status, limit, offset })}`),
  getWithdrawal: (id: string) => apiFetch<MerchantWithdrawal>(`/owner/withdrawals/${id}`),
  approveWithdrawal: (id: string, comment: string | null) => apiFetch<MerchantWithdrawal>(`/owner/withdrawals/${id}/approve`, { method: "POST", body: { comment } }),
  rejectWithdrawal: (id: string, comment: string | null) => apiFetch<MerchantWithdrawal>(`/owner/withdrawals/${id}/reject`, { method: "POST", body: { comment } }),
  markWithdrawalPaid: (id: string, comment: string | null) => apiFetch<MerchantWithdrawal>(`/owner/withdrawals/${id}/mark-paid`, { method: "POST", body: { comment } }),
};
