"use client";

import { useTranslations } from "next-intl";

import { useAppFormat } from "@/features/i18n/use-app-format";
import type { InvoiceTimeline, TimelineEvent } from "@/lib/api/types";

import styles from "./invoice-timeline.module.css";

function eventDotClass(type: string): string {
  if (type === "invoice.paid" || type === "webhook.success" || type === "deposit.credited") return styles.paid;
  if (type === "invoice.cancelled" || type === "deposit.failed" || type === "webhook.failed") return styles.failed;
  return styles.pending;
}

export function InvoiceTimelineSection({ timeline }: { timeline: InvoiceTimeline }) {
  const t = useTranslations("invoices.timeline");
  const format = useAppFormat();

  function eventLabel(event: TimelineEvent): string {
    const key = event.type.replaceAll(".", "_");
    return t.has(`events.${key}`) ? t(`events.${key}`) : event.type;
  }

  function eventMeta(event: TimelineEvent): string | null {
    switch (event.type) {
      case "invoice.balance_credited":
        return typeof event.data.amount === "string" ? t("balanceCredited", { amount: event.data.amount }) : null;
      case "deposit.detected":
        return typeof event.data.tx_hash === "string" ? event.data.tx_hash : null;
      case "webhook.pending":
      case "webhook.success":
      case "webhook.failed":
        return t("attemptCount", { attempts: Number(event.data.attempts ?? 0), max: Number(event.data.max_attempts ?? 0) });
      default:
        return null;
    }
  }

  const { deposit, ledger_entry: ledgerEntry, webhook_deliveries: deliveries } = timeline;

  return <div className={styles.section}>
    <h3 className={styles.sectionTitle}>{t("title")}</h3>
    {timeline.events.length === 0 ? <p className={styles.empty}>{t("empty")}</p>
      : <ol className={styles.list}>
        {timeline.events.map((event, index) => <li key={`${event.type}-${event.at}-${index}`} className={`${styles.item} ${eventDotClass(event.type)}`}>
          <div className={styles.itemHead}>
            <span className={styles.itemLabel}>{eventLabel(event)}</span>
            <span className={styles.itemTime}>{format.dateTime(event.at)}</span>
          </div>
          {eventMeta(event) && <div className={styles.itemMeta}>{eventMeta(event)}</div>}
        </li>)}
      </ol>}

    {deposit && <>
      <h3 className={styles.sectionTitle} style={{ marginTop: 20 }}>{t("depositTitle")}</h3>
      <div className={styles.grid}>
        <div><span>{t("depositTxHash")}</span><strong>{deposit.tx_hash ?? "—"}</strong></div>
        <div><span>{t("depositConfirmations")}</span><strong>{deposit.confirmations}/{deposit.required_confirmations}</strong></div>
        <div><span>{t("depositReceived")}</span><strong>{deposit.received_amount ?? "—"} USDT</strong></div>
      </div>
    </>}

    {ledgerEntry && <>
      <h3 className={styles.sectionTitle} style={{ marginTop: 20 }}>{t("ledgerTitle")}</h3>
      <p className={styles.itemMeta}>{t("balanceCredited", { amount: ledgerEntry.amount })}</p>
    </>}

    <h3 className={styles.sectionTitle} style={{ marginTop: 20 }}>{t("webhooksTitle")}</h3>
    {deliveries.length === 0 ? <p className={styles.empty}>{t("webhooksEmpty")}</p>
      : <div className={styles.grid}>
        {deliveries.map((delivery, index) => <div key={`${delivery.webhook_id}-${index}`}>
          <span>{t("webhookStatus")}</span>
          <strong>{delivery.status}</strong>
          <div className={styles.itemMeta}>{t("attemptCount", { attempts: delivery.attempts, max: delivery.max_attempts })}</div>
          {delivery.last_error && <div className={styles.itemMeta}>{delivery.last_error}</div>}
        </div>)}
      </div>}
  </div>;
}
