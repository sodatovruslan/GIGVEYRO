import { apiFetch } from "@/lib/api/client";
import type { LedgerEntry, Paginated, PaymentRequisite, TrafficSettings, Wallet } from "@/lib/api/types";

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
  requisites: () => apiFetch<PaymentRequisite[]>("/requisites"),
  createRequisite: (input: RequisiteCreateInput) => apiFetch<PaymentRequisite>("/requisites", { method: "POST", body: input }),
  updateRequisite: (id: string, input: Pick<PaymentRequisite, "bank_name" | "holder_name" | "phone_number">) => apiFetch<PaymentRequisite>(`/requisites/${id}`, { method: "PATCH", body: input }),
  requisiteAction: (id: string, action: "activate" | "deactivate" | "archive") => apiFetch<PaymentRequisite>(`/requisites/${id}/${action}`, { method: "POST" }),
  traffic: () => apiFetch<TrafficSettings>("/traffic"),
  setTraffic: (enabled: boolean) => apiFetch<TrafficSettings>(`/traffic/${enabled ? "enable" : "disable"}`, { method: "POST" }),
};
