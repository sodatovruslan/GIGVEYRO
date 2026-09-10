"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";

import { useAppFormat } from "@/features/i18n/use-app-format";
import { useEnumLabels } from "@/features/i18n/use-enum-labels";
import { useLocalizedError } from "@/features/i18n/use-localized-error";
import { publicInvoiceApi } from "@/lib/api/invoices";
import { ApiError } from "@/lib/api/error";
import type { PublicInvoice } from "@/lib/api/types";

import styles from "./page.module.css";

const POLL_INTERVAL_MS = 5000;

export default function PublicInvoicePayPage() {
  const publicId = useParams<{ publicId: string }>().publicId;
  const t = useTranslations("invoices.pay");
  const labels = useEnumLabels();
  const format = useAppFormat();
  const localizeError = useLocalizedError();
  const [invoice, setInvoice] = useState<PublicInvoice | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notFound, setNotFound] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const result = await publicInvoiceApi.get(publicId);
        if (!active) return;
        setInvoice(result);
        setError("");
        setNotFound(false);
      } catch (reason) {
        if (!active) return;
        if (reason instanceof ApiError && reason.status === 404) setNotFound(true);
        else setError(localizeError(reason));
      } finally {
        if (active) setLoading(false);
      }
    }
    void load();
    const interval = setInterval(() => {
      void load();
    }, POLL_INTERVAL_MS);
    return () => { active = false; clearInterval(interval); };
  }, [publicId, localizeError]);

  async function copyAddress() {
    if (!invoice) return;
    try { await navigator.clipboard.writeText(invoice.deposit_address); setCopied(true); }
    catch { /* clipboard access can be denied - the address remains visible for manual copy */ }
  }

  return <main className={styles.page}>
    <div className={styles.card}>
      <span className={styles.eyebrow}>GigaPay</span>
      <h1>{t("title")}</h1>
      {!loading && !notFound && !error && <p className={styles.row}>{t("subtitle")}</p>}
      {loading ? <div className={styles.state}>{t("loading")}</div>
        : notFound ? <div className={styles.state}>{t("notFound")}</div>
        : error ? <div className={styles.state}>{error}</div>
        : invoice && <>
            <div className={styles.amount}><strong>{invoice.amount}</strong><span>USDT · TRC20</span></div>
            {invoice.description && <div className={styles.row}><span>{invoice.description}</span></div>}
            <div className={styles.row}>
              <span>{t("addressLabel")}</span>
              <div className={styles.address}>
                <code>{invoice.deposit_address}</code>
                <button type="button" onClick={() => void copyAddress()}>{copied ? t("copied") : t("copyAddress")}</button>
              </div>
            </div>
            <div className={styles.row}><span>{t("statusLabel")}</span><span className={`${styles.status} ${styles[invoice.status]}`}>{labels.invoice(invoice.status)}</span></div>
            <div className={styles.row}><span>{t("expiresLabel")}</span><span>{format.dateTime(invoice.expires_at)}</span></div>
            {invoice.status === "pending_payment" && <p className={styles.state}>{t("waiting")}</p>}
          </>}
    </div>
  </main>;
}
