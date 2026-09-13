import { apiFetch } from "@/lib/api/client";
import type { Invoice, InvoiceStatus, InvoiceTimeline, Paginated, PublicInvoice } from "@/lib/api/types";

export const invoicesApi = {
  list: (status?: InvoiceStatus, limit = 20, offset = 0) => apiFetch<Paginated<Invoice>>(`/merchant/invoices?${new URLSearchParams({ ...(status ? { status } : {}), limit: String(limit), offset: String(offset) })}`),
  get: (id: string) => apiFetch<Invoice>(`/merchant/invoices/${id}`),
  timeline: (id: string) => apiFetch<InvoiceTimeline>(`/merchant/invoices/${id}/timeline`),
  create: (input: { amount: string; description: string | null; external_reference: string | null }) => apiFetch<Invoice>("/merchant/invoices", { method: "POST", body: input }),
  cancel: (id: string) => apiFetch<Invoice>(`/merchant/invoices/${id}/cancel`, { method: "POST" }),
};

export const publicInvoiceApi = {
  get: (publicId: string) => apiFetch<PublicInvoice>(`/invoices/${publicId}`),
};
