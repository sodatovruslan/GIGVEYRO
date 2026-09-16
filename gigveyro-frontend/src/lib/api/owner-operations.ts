import { apiFetch } from "@/lib/api/client";
import type { AuditLogEntry, FeePolicy, FeePreview, FeeType, InsuranceReservePolicy, InsuranceReservePolicyInput, IntegrationDiagnostics, LivePayoutReadiness, MerchantWithdrawal, Paginated, PayoutDestination, PayoutIntent, PayoutNetwork, PayoutPolicy, PayoutPolicyInput, PayoutStatus, ProfitEntry, ProfitSummary, RiskPolicy, RiskPolicyInput, RiskPreview, TreasurySummary } from "@/lib/api/types";

export const auditActions = ["account.create", "account.update", "account.block", "account.unblock", "account.reset_password", "wallet.allocate", "wallet.adjust_insurance", "wallet.manual_adjust", "wallet.insurance_reserve_denied", "fiat.allocate", "fiat.convert", "fee_policy.created", "fee_policy.activated", "fee_policy.disabled", "risk_policy.created", "risk_policy.activated", "risk_policy.disabled", "insurance_reserve_policy.created", "insurance_reserve_policy.activated", "payout.intent_created", "payout.risk_checked", "payout.approved", "payout.rejected", "payout.queued", "payout.execution_started", "payout.simulated_succeeded", "payout.failed", "payout.reconciliation_required", "payout.reconciled", "payout.cancelled", "payout_address.created", "payout_address.disabled", "payout_network.disabled", "deal.complete", "deal.release", "appeal.review", "appeal.resolve", "withdrawal.approve", "withdrawal.reject", "withdrawal.mark_paid"] as const;
export const auditEntityTypes = ["account", "wallet", "fiat_wallet", "fiat_conversion", "fee_policy", "fee_policy_component", "risk_policy", "insurance_reserve_policy", "payout", "payout_address", "payout_network", "deal", "appeal", "withdrawal"] as const;

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
  insuranceReservePolicy: () => apiFetch<InsuranceReservePolicy>("/api/v1/owner/insurance-reserve-policy"),
  createInsuranceReservePolicy: (body: InsuranceReservePolicyInput) => apiFetch<InsuranceReservePolicy>("/api/v1/owner/insurance-reserve-policies", { method: "POST", body }),
  activateInsuranceReservePolicy: (id: string) => apiFetch<InsuranceReservePolicy>(`/api/v1/owner/insurance-reserve-policies/${id}/activate`, { method: "POST" }),
  payouts: (status?: PayoutStatus, offset = 0) => apiFetch<Paginated<PayoutIntent>>(`/api/v1/owner/payouts?${queryString({ status, limit: 20, offset })}`),
  payout: (id: string) => apiFetch<PayoutIntent>(`/api/v1/owner/payouts/${id}`),
  approvePayout: (id: string, comment?: string) => apiFetch<PayoutIntent>(`/api/v1/owner/payouts/${id}/approve`, { method: "POST", body: { comment: comment || null } }),
  rejectPayout: (id: string, comment?: string) => apiFetch<PayoutIntent>(`/api/v1/owner/payouts/${id}/reject`, { method: "POST", body: { comment: comment || null } }),
  cancelPayout: (id: string, comment?: string) => apiFetch<PayoutIntent>(`/api/v1/owner/payouts/${id}/cancel`, { method: "POST", body: { comment: comment || null } }),
  queuePayout: (id: string, outcome: "succeeded" | "failed" | "pending" | "unknown") => apiFetch<PayoutIntent>(`/api/v1/owner/payouts/${id}/queue`, { method: "POST", body: { outcome } }),
  executePayout: (id: string) => apiFetch<PayoutIntent>(`/api/v1/owner/payouts/${id}/execute`, { method: "POST" }),
  reconcilePayout: (id: string, outcome?: "succeeded" | "failed" | "pending" | "unknown") => apiFetch<PayoutIntent>(`/api/v1/owner/payouts/${id}/reconcile`, { method: "POST", body: { outcome: outcome || null } }),
  beginManualPayout: (id: string) => apiFetch<PayoutIntent>(`/api/v1/owner/payouts/${id}/manual`, { method: "POST" }),
  completeManualPayout: (id: string, externalReference: string, evidence: string) => apiFetch<PayoutIntent>(`/api/v1/owner/payouts/${id}/manual/complete`, { method: "POST", body: { external_reference: externalReference, evidence } }),
  payoutPolicy: () => apiFetch<PayoutPolicy>("/api/v1/owner/payout-policy"),
  createPayoutPolicy: (body: PayoutPolicyInput) => apiFetch<PayoutPolicy>("/api/v1/owner/payout-policies", { method: "POST", body }),
  activatePayoutPolicy: (id: string) => apiFetch<PayoutPolicy>(`/api/v1/owner/payout-policies/${id}/activate`, { method: "POST" }),
  payoutReadiness: () => apiFetch<LivePayoutReadiness>("/api/v1/owner/payout-readiness"),
  payoutAddresses: () => apiFetch<PayoutDestination[]>("/api/v1/owner/payout-addresses"),
  createPayoutAddress: (body: { beneficiary_account_id: string; label: string; asset: "USDT"; network: "TRC20"; address: string }) => apiFetch<PayoutDestination>("/api/v1/owner/payout-addresses", { method: "POST", body }),
  disablePayoutAddress: (id: string) => apiFetch<PayoutDestination>(`/api/v1/owner/payout-addresses/${id}/disable`, { method: "POST" }),
  payoutNetworks: () => apiFetch<PayoutNetwork[]>("/api/v1/owner/payout-networks"),
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
