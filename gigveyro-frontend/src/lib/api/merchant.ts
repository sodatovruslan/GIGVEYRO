import { apiFetch } from "@/lib/api/client";
import type { FeeComponent, LedgerEntry, MerchantProfile, MerchantStatistics, MerchantWallet, MerchantWithdrawal, Paginated } from "@/lib/api/types";

export const merchantApi = {
  wallet: () => apiFetch<MerchantWallet>("/merchant/wallet"),
  ledger: () => apiFetch<Paginated<LedgerEntry>>("/merchant/wallet/ledger?limit=100&offset=0"),
  fee: () => apiFetch<FeeComponent>("/merchant/fees"),
  statistics: () => apiFetch<MerchantStatistics>("/merchant/statistics"),
  profile: () => apiFetch<MerchantProfile>("/merchant/profile"),
  updateProfile: (input: { store_name: string | null; description: string | null; support_contact: string | null }) => apiFetch<MerchantProfile>("/merchant/profile", { method: "PUT", body: input }),
  withdrawals: (status?: MerchantWithdrawal["status"], limit = 20, offset = 0) => apiFetch<Paginated<MerchantWithdrawal>>(`/merchant/withdrawals?${new URLSearchParams({ ...(status ? { status } : {}), limit: String(limit), offset: String(offset) })}`),
  getWithdrawal: (id: string) => apiFetch<MerchantWithdrawal>(`/merchant/withdrawals/${id}`),
  createWithdrawal: (input: { amount: string; destination_type: MerchantWithdrawal["destination_type"]; destination: string; comment: string | null }) => apiFetch<MerchantWithdrawal>("/merchant/withdrawals", { method: "POST", body: input }),
  cancelWithdrawal: (id: string) => apiFetch<MerchantWithdrawal>(`/merchant/withdrawals/${id}/cancel`, { method: "POST" }),
};

export async function downloadMerchantInvoicesCsv(): Promise<void> {
  const response = await fetch("/api/backend/merchant/reports/invoices", { credentials: "same-origin" });
  if (!response.ok) throw new Error("export failed");
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "invoices.csv";
  link.click();
  URL.revokeObjectURL(url);
}
