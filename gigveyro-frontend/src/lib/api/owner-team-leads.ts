import { apiFetch } from "@/lib/api/client";
import type { Account, Paginated, TeamLeadWithdrawal } from "@/lib/api/types";

function queryString(values: Record<string, string | number | undefined>) {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== "") params.set(key, String(value));
  });
  return params.toString();
}

export const ownerTeamLeadsApi = {
  assign: (userId: string, teamLeadId: string | null) =>
    apiFetch<Account>(`/owner/accounts/${userId}/team-lead`, { method: "POST", body: { team_lead_id: teamLeadId } }),
  withdrawals: {
    list: (status?: TeamLeadWithdrawal["status"], limit = 20, offset = 0) =>
      apiFetch<Paginated<TeamLeadWithdrawal>>(`/owner/team-lead-withdrawals?${queryString({ status, limit, offset })}`),
    get: (id: string) => apiFetch<TeamLeadWithdrawal>(`/owner/team-lead-withdrawals/${id}`),
    approve: (id: string, comment: string | null) =>
      apiFetch<TeamLeadWithdrawal>(`/owner/team-lead-withdrawals/${id}/approve`, { method: "POST", body: { comment } }),
    reject: (id: string, comment: string | null) =>
      apiFetch<TeamLeadWithdrawal>(`/owner/team-lead-withdrawals/${id}/reject`, { method: "POST", body: { comment } }),
    markPaid: (id: string, comment: string | null) =>
      apiFetch<TeamLeadWithdrawal>(`/owner/team-lead-withdrawals/${id}/mark-paid`, { method: "POST", body: { comment } }),
  },
};
