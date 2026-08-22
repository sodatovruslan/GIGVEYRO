import { apiFetch } from "@/lib/api/client";
import type { LedgerEntry, MerchantWallet, MerchantWithdrawal, Paginated } from "@/lib/api/types";

export const merchantApi = {
  wallet: () => apiFetch<MerchantWallet>("/merchant/wallet"),
  ledger: () => apiFetch<Paginated<LedgerEntry>>("/merchant/wallet/ledger?limit=100&offset=0"),
  withdrawals: (status?: MerchantWithdrawal["status"], limit = 20, offset = 0) => apiFetch<Paginated<MerchantWithdrawal>>(`/merchant/withdrawals?${new URLSearchParams({ ...(status ? { status } : {}), limit: String(limit), offset: String(offset) })}`),
  getWithdrawal: (id: string) => apiFetch<MerchantWithdrawal>(`/merchant/withdrawals/${id}`),
  createWithdrawal: (input: { amount: string; destination_type: MerchantWithdrawal["destination_type"]; destination: string; comment: string | null }) => apiFetch<MerchantWithdrawal>("/merchant/withdrawals", { method: "POST", body: input }),
  cancelWithdrawal: (id: string) => apiFetch<MerchantWithdrawal>(`/merchant/withdrawals/${id}/cancel`, { method: "POST" }),
};
