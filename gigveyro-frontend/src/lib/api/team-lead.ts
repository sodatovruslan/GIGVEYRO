import { apiFetch } from "@/lib/api/client";
import type {
  Deal,
  LedgerEntry,
  Paginated,
  TeamLeadDashboard,
  TeamLeadWithdrawal,
  TeamMember,
} from "@/lib/api/types";

function queryString(values: Record<string, string | number | boolean | undefined>) {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== "") params.set(key, String(value));
  });
  return params.toString();
}

export const teamLeadApi = {
  dashboard: () => apiFetch<TeamLeadDashboard>("/team-lead/dashboard"),
  team: (isActive?: boolean, search?: string, limit = 20, offset = 0) =>
    apiFetch<Paginated<TeamMember>>(`/team-lead/team?${queryString({ is_active: isActive, search, limit, offset })}`),
  deals: (status?: Deal["status"], limit = 20, offset = 0) =>
    apiFetch<Paginated<Deal>>(`/team-lead/deals?${queryString({ status, limit, offset })}`),
  profitLedger: (limit = 20, offset = 0) =>
    apiFetch<Paginated<LedgerEntry>>(`/team-lead/profit/ledger?${queryString({ limit, offset })}`),
  withdrawals: {
    create: (input: { amount: string; destination_type: TeamLeadWithdrawal["destination_type"]; destination: string; comment?: string | null }) =>
      apiFetch<TeamLeadWithdrawal>("/team-lead/withdrawals", { method: "POST", body: input }),
    list: (status?: TeamLeadWithdrawal["status"], limit = 20, offset = 0) =>
      apiFetch<Paginated<TeamLeadWithdrawal>>(`/team-lead/withdrawals?${queryString({ status, limit, offset })}`),
    get: (id: string) => apiFetch<TeamLeadWithdrawal>(`/team-lead/withdrawals/${id}`),
    cancel: (id: string) => apiFetch<TeamLeadWithdrawal>(`/team-lead/withdrawals/${id}/cancel`, { method: "POST" }),
  },
};
