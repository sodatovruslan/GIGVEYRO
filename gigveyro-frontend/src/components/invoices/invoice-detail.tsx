"use client";

import { useTranslations } from "next-intl";

import { useAppFormat } from "@/features/i18n/use-app-format";
import { useEnumLabels } from "@/features/i18n/use-enum-labels";
import type { Invoice } from "@/lib/api/types";

import styles from "./invoice-detail.module.css";

export function InvoiceDetailGrid({ invoice, paymentLink, onCopyLink, linkCopied }: { invoice: Invoice; paymentLink: string; onCopyLink: () => void; linkCopied: boolean }) {
  const t = useTranslations("invoices");
  const common = useTranslations("common");
  const labels = useEnumLabels();
  const format = useAppFormat();
  return <div className={styles.grid}>
    <div><span>{common("status")}</span><strong><span className={`${styles.status} ${styles[invoice.status]}`}>{labels.invoice(invoice.status)}</span></strong></div>
    <div><span>{common("amount")}</span><strong>{invoice.amount} USDT</strong></div>
    <div><span>{common("date")}</span><strong>{format.dateTime(invoice.created_at)}</strong></div>
    {invoice.description && <div><span>{t("description")}</span><strong>{invoice.description}</strong></div>}
    {invoice.external_reference && <div><span>{t("externalReference")}</span><strong>{invoice.external_reference}</strong></div>}
    {invoice.paid_at && <div><span>{labels.invoice("paid")}</span><strong>{format.dateTime(invoice.paid_at)}</strong></div>}
    {invoice.cancelled_at && <div><span>{t("cancelAction")}</span><strong>{format.dateTime(invoice.cancelled_at)}</strong></div>}
    {invoice.status === "pending_payment" && (
      <div><span>{t("paymentLink")}</span><strong><code>{paymentLink}</code><br /><button type="button" onClick={onCopyLink}>{linkCopied ? t("linkCopied") : t("copyLink")}</button></strong></div>
    )}
    <div><span>ID</span><code>{invoice.id}</code></div>
  </div>;
}
