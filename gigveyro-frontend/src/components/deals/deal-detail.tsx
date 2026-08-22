"use client";

import { useTranslations } from "next-intl";

import { useAppFormat } from "@/features/i18n/use-app-format";
import { useEnumLabels } from "@/features/i18n/use-enum-labels";
import type { Deal } from "@/lib/api/types";

import listStyles from "./deals-page.module.css";
import styles from "./deal-detail.module.css";

export function DealDetailGrid({ deal }: { deal: Deal }) {
  const t = useTranslations("deals");
  const common = useTranslations("common");
  const labels = useEnumLabels();
  const format = useAppFormat();
  return <div className={styles.grid}>
    <div><span>{common("status")}</span><strong><span className={`${listStyles.status} ${listStyles[deal.status]}`}>{labels.deal(deal.status)}</span></strong></div>
    <div><span>{common("amount")}</span><strong>{deal.amount_tjs} TJS</strong></div>
    <div><span>{t("rate")}</span><strong>{deal.exchange_rate || "—"}</strong></div>
    <div><span>USDT</span><strong>{deal.amount_usdt || "—"}</strong></div>
    <div><span>{t("merchant")}</span><strong><code>{deal.merchant_id}</code></strong></div>
    {deal.user_id && <div><span>{t("user")}</span><strong><code>{deal.user_id}</code></strong></div>}
    <div><span>{t("requisite")}</span><strong>{deal.requisite_bank_name || "—"}<small>{deal.requisite_masked_card_number || common("notSpecified")}</small></strong></div>
    <div><span>{common("date")}</span><strong>{format.dateTime(deal.created_at)}</strong></div>
    <div><span>{t("deadline")}</span><strong>{format.dateTime(deal.expires_at)}</strong></div>
    {deal.accepted_at && <div><span>{t("accepted")}</span><strong>{format.dateTime(deal.accepted_at)}</strong></div>}
    {deal.completed_at && <div><span>{t("completed")}</span><strong>{format.dateTime(deal.completed_at)}</strong></div>}
    {deal.cancelled_at && <div><span>{t("cancelledAt")}</span><strong>{format.dateTime(deal.cancelled_at)}</strong></div>}
    <div><span>ID</span><code>{deal.id}</code></div>
  </div>;
}
