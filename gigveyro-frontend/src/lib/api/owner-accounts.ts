import { apiFetch } from "@/lib/api/client";
import type { Account, FiatAllocation, FiatBalanceList, FiatConversion, FiatConversionPreview, FiatCurrency, FiatLedgerEntry, InsuranceReserveWalletView, LedgerEntry, MerchantWallet, Paginated, PaymentRequisite, TrafficSettings, UserRole, Wallet } from "@/lib/api/types";

export interface AccountFilters {
  search?: string;
  role?: UserRole | "";
  isActive?: boolean | "";
  limit?: number;
  offset?: number;
}

export interface CreateAccountInput {
  username: string;
  password: string;
  role: Exclude<UserRole, "owner">;
  full_name: string;
  email: string | null;
  phone: string | null;
}

function queryString(filters: AccountFilters) {
  const query = new URLSearchParams();
  if (filters.search) query.set("search", filters.search);
  if (filters.role) query.set("role", filters.role);
  if (filters.isActive !== "" && filters.isActive !== undefined) query.set("is_active", String(filters.isActive));
  query.set("limit", String(filters.limit || 20));
  query.set("offset", String(filters.offset || 0));
  return query.toString();
}

export const ownerAccountsApi = {
  list: (filters: AccountFilters = {}) => apiFetch<Paginated<Account>>(`/owner/accounts?${queryString(filters)}`),
  get: (id: string) => apiFetch<Account>(`/owner/accounts/${id}`),
  create: (input: CreateAccountInput) => apiFetch<Account>("/owner/accounts", { method: "POST", body: input }),
  update: (id: string, input: Pick<Account, "full_name" | "email" | "phone">) => apiFetch<Account>(`/owner/accounts/${id}`, { method: "PATCH", body: input }),
  setActive: (id: string, active: boolean) => apiFetch<Account>(`/owner/accounts/${id}/${active ? "unblock" : "block"}`, { method: "POST" }),
  resetPassword: (id: string, newPassword: string) => apiFetch<void>(`/owner/accounts/${id}/reset-password`, { method: "POST", body: { new_password: newPassword } }),
  userWallet: (id: string) => apiFetch<Wallet>(`/owner/accounts/${id}/wallet`),
  insuranceReserve: (id: string) => apiFetch<InsuranceReserveWalletView>(`/owner/accounts/${id}/wallet/insurance-reserve`),
  merchantWallet: (id: string) => apiFetch<MerchantWallet>(`/owner/accounts/${id}/merchant-wallet`),
  ledger: (id: string, merchant: boolean) => apiFetch<Paginated<LedgerEntry>>(`/owner/accounts/${id}/${merchant ? "merchant-wallet/ledger" : "wallet/ledger"}?limit=20&offset=0`),
  requisites: (id: string) => apiFetch<PaymentRequisite[]>(`/owner/accounts/${id}/requisites`),
  traffic: (id: string) => apiFetch<TrafficSettings>(`/owner/accounts/${id}/traffic`),
  adjustWallet: (id: string, action: "allocate" | "insurance" | "adjust", amount: string, description: string) =>
    apiFetch<Wallet>(`/owner/accounts/${id}/wallet/${action}`, {
      method: "POST",
      body: action === "adjust" ? { amount, reason: description } : { amount, description },
    }),
  fiatBalances: (id: string) => apiFetch<FiatBalanceList>(`/owner/accounts/${id}/fiat-wallets`),
  fiatLedger: (id: string, offset = 0) => apiFetch<Paginated<FiatLedgerEntry>>(`/owner/accounts/${id}/fiat-wallets/ledger?limit=20&offset=${offset}`),
  fiatConversions: (id: string, offset = 0) => apiFetch<Paginated<FiatConversion>>(`/owner/fiat-conversions?account_id=${encodeURIComponent(id)}&limit=20&offset=${offset}`),
  allocateFiat: (id: string, currency: FiatCurrency, amount: string, comment: string, idempotencyKey: string) => apiFetch<FiatAllocation>(`/owner/accounts/${id}/fiat-wallets/allocate`, { method: "POST", body: { currency, amount, comment: comment || null, idempotency_key: idempotencyKey } }),
  previewFiatConversion: (fromCurrency: FiatCurrency, toCurrency: FiatCurrency, sourceAmount: string) => apiFetch<FiatConversionPreview>("/owner/fiat-conversions/preview", { method: "POST", body: { from_currency: fromCurrency, to_currency: toCurrency, source_amount: sourceAmount } }),
  convertFiat: (id: string, fromCurrency: FiatCurrency, toCurrency: FiatCurrency, sourceAmount: string, comment: string, idempotencyKey: string) => apiFetch<FiatConversion>(`/owner/accounts/${id}/fiat-conversions`, { method: "POST", body: { from_currency: fromCurrency, to_currency: toCurrency, source_amount: sourceAmount, comment: comment || null, idempotency_key: idempotencyKey } }),
};
