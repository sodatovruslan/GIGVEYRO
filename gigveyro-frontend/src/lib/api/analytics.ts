import { apiFetch } from "@/lib/api/client";

export interface DashboardSummary {
  accounts: { users_total: number; users_active: number; users_blocked: number; merchants_total: number; merchants_active: number; merchants_blocked: number };
  traffic: { users_enabled: number };
  deals: { total: number; available: number; accepted: number; payment_pending: number; completed: number; disputed: number; cancelled: number };
  deposits: { total: number; credited: number; pending: number; amount_credited_usdt: string };
  withdrawals: { total: number; pending: number; approved: number; paid: number; rejected: number; amount_paid_usdt: string };
  appeals: { open: number; under_review: number; resolved: number };
  financials: { total_user_available_usdt: string; total_user_insurance_usdt: string; total_user_frozen_usdt: string; total_merchant_available_usdt: string; total_merchant_held_usdt: string; total_credited_deposits_usdt: string; total_paid_withdrawals_usdt: string; total_completed_deal_volume_tjs: string; total_completed_deal_volume_usdt: string };
}

export interface Activity { type: string; entity_id: string; public_id: string | null; description: string; created_at: string }
export interface DealAnalytics { total_deals: number; completed_deals: number; cancelled_deals: number; disputed_deals: number; total_volume_tjs: string; total_volume_usdt: string; average_deal_tjs: string; average_deal_usdt: string; completion_rate: string; dispute_rate: string; average_completion_time_seconds: number | null }
export interface AccountAnalytics { users_total: number; users_active: number; users_blocked: number; merchants_total: number; merchants_active: number; merchants_blocked: number; traffic_enabled_users: number; users_with_requisites: number; users_without_requisites: number }
export interface FinancialFlow { deposits_credited_usdt: string; deal_settlements_usdt: string; withdrawals_paid_usdt: string; merchant_balances_usdt: string }
export interface BalanceIntegrity { user_wallet_total_usdt: string; merchant_wallet_total_usdt: string; credited_deposits_usdt: string; paid_withdrawals_usdt: string; status: "ok" }
export interface DealTimeSeriesPoint { period: string; deals: number; completed: number; volume_tjs: string; volume_usdt: string }

type AnalyticsPeriod = "today" | "7d" | "30d" | "90d";

function timeSeriesQuery(period: AnalyticsPeriod) {
  const dateTo = new Date();
  const dateFrom = new Date(dateTo);
  const days = period === "today" ? 0 : Number.parseInt(period, 10) - 1;
  dateFrom.setUTCDate(dateFrom.getUTCDate() - days);
  dateFrom.setUTCHours(0, 0, 0, 0);
  const granularity = period === "90d" ? "week" : "day";
  return new URLSearchParams({ date_from: dateFrom.toISOString(), date_to: dateTo.toISOString(), granularity }).toString();
}

const root = "/api/v1/owner";
export const analyticsApi = {
  summary: () => apiFetch<DashboardSummary>(`${root}/dashboard/summary`),
  activity: () => apiFetch<Activity[]>(`${root}/dashboard/activity?limit=12`),
  bundle: (period: AnalyticsPeriod) => Promise.all([
    apiFetch<DealAnalytics>(`${root}/analytics/deals?period=${period}`),
    apiFetch<DealTimeSeriesPoint[]>(`${root}/analytics/deals/timeseries?${timeSeriesQuery(period)}`),
    apiFetch<AccountAnalytics>(`${root}/analytics/accounts`),
    apiFetch<FinancialFlow>(`${root}/analytics/financial-flow?period=${period}`),
    apiFetch<BalanceIntegrity>(`${root}/analytics/balance-integrity`),
  ]).then(([deals, timeseries, accounts, flow, integrity]) => ({ deals, timeseries, accounts, flow, integrity })),
};
