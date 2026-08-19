import { apiFetch } from "@/lib/api/client";
import type { Account, LedgerEntry, MerchantWallet, Paginated, UserRole, Wallet } from "@/lib/api/types";

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
  merchantWallet: (id: string) => apiFetch<MerchantWallet>(`/owner/accounts/${id}/merchant-wallet`),
  ledger: (id: string, merchant: boolean) => apiFetch<Paginated<LedgerEntry>>(`/owner/accounts/${id}/${merchant ? "merchant-wallet/ledger" : "wallet/ledger"}?limit=20&offset=0`),
  adjustWallet: (id: string, action: "allocate" | "insurance" | "adjust", amount: string, description: string) =>
    apiFetch<Wallet>(`/owner/accounts/${id}/wallet/${action}`, {
      method: "POST",
      body: action === "adjust" ? { amount, reason: description } : { amount, description },
    }),
};
