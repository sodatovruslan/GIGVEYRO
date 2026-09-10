import { apiFetch } from "@/lib/api/client";
import type { FiatBalanceList, FiatConversion, FiatLedgerEntry, LedgerEntry, Paginated, PaymentRequisite, TrafficSettings, UserWithdrawal, Wallet } from "@/lib/api/types";

export interface RequisiteCreateInput {
  type: "bank_card";
  bank_name: string;
  holder_name: string;
  card_number: string;
  phone_number: string | null;
}

export const userApi = {
  wallet: () => apiFetch<Wallet>("/wallet"),
  ledger: () => apiFetch<Paginated<LedgerEntry>>("/wallet/ledger?limit=100&offset=0"),
  fiatBalances: () => apiFetch<FiatBalanceList>("/fiat-wallets"),
  fiatLedger: (offset = 0) => apiFetch<Paginated<FiatLedgerEntry>>(`/fiat-wallets/ledger?limit=20&offset=${offset}`),
  fiatConversions: (offset = 0) => apiFetch<Paginated<FiatConversion>>(`/fiat-wallets/conversions?limit=20&offset=${offset}`),
  requisites: () => apiFetch<PaymentRequisite[]>("/requisites"),
  createRequisite: (input: RequisiteCreateInput) => apiFetch<PaymentRequisite>("/requisites", { method: "POST", body: input }),
  updateRequisite: (id: string, input: Pick<PaymentRequisite, "bank_name" | "holder_name" | "phone_number">) => apiFetch<PaymentRequisite>(`/requisites/${id}`, { method: "PATCH", body: input }),
  requisiteAction: (id: string, action: "activate" | "deactivate" | "archive") => apiFetch<PaymentRequisite>(`/requisites/${id}/${action}`, { method: "POST" }),
  traffic: () => apiFetch<TrafficSettings>("/traffic"),
  setTraffic: (enabled: boolean) => apiFetch<TrafficSettings>(`/traffic/${enabled ? "enable" : "disable"}`, { method: "POST" }),
  withdrawals: (status?: UserWithdrawal["status"], limit = 20, offset = 0) => apiFetch<Paginated<UserWithdrawal>>(`/withdrawals?${new URLSearchParams({ ...(status ? { status } : {}), limit: String(limit), offset: String(offset) })}`),
  getWithdrawal: (id: string) => apiFetch<UserWithdrawal>(`/withdrawals/${id}`),
  createWithdrawal: (input: { amount: string; destination_type: UserWithdrawal["destination_type"]; destination: string; comment: string | null }) => apiFetch<UserWithdrawal>("/withdrawals", { method: "POST", body: input }),
  cancelWithdrawal: (id: string) => apiFetch<UserWithdrawal>(`/withdrawals/${id}/cancel`, { method: "POST" }),
};
