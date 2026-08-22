"use client";

import { useTranslations } from "next-intl";

import { useAppFormat } from "@/features/i18n/use-app-format";
import { useEnumLabels } from "@/features/i18n/use-enum-labels";
import type { MerchantWithdrawal } from "@/lib/api/types";

import styles from "./withdrawal-detail.module.css";

export function WithdrawalDetailGrid({ withdrawal, owner }: { withdrawal: MerchantWithdrawal; owner: boolean }) {
  const t = useTranslations("withdrawals");
  const common = useTranslations("common");
  const labels = useEnumLabels();
  const format = useAppFormat();
  return <div className={styles.grid}>
    <div><span>{common("status")}</span><strong><span className={`${styles.status} ${styles[withdrawal.status]}`}>{labels.withdrawal(withdrawal.status)}</span></strong></div>
    <div><span>{common("amount")}</span><strong>{withdrawal.amount} {withdrawal.currency.toUpperCase()}</strong></div>
    <div><span>{t("destinationType")}</span><strong>{labels.destination(withdrawal.destination_type)}</strong></div>
    <div><span>{t("destination")}</span><strong><code>{withdrawal.destination}</code></strong></div>
    {owner && <div><span>{t("merchant")}</span><strong><code>{withdrawal.merchant_id}</code></strong></div>}
    <div><span>{common("date")}</span><strong>{format.dateTime(withdrawal.created_at)}</strong></div>
    {withdrawal.approved_at && <div><span>{t("approve")}</span><strong>{format.dateTime(withdrawal.approved_at)}</strong></div>}
    {withdrawal.rejected_at && <div><span>{t("reject")}</span><strong>{format.dateTime(withdrawal.rejected_at)}</strong></div>}
    {withdrawal.paid_at && <div><span>{t("markPaid")}</span><strong>{format.dateTime(withdrawal.paid_at)}</strong></div>}
    {withdrawal.cancelled_at && <div><span>{t("cancelAction")}</span><strong>{format.dateTime(withdrawal.cancelled_at)}</strong></div>}
    {withdrawal.comment && <div><span>{t("comment")}</span><strong>{withdrawal.comment}</strong></div>}
    {withdrawal.owner_comment && <div><span>{t("ownerComment")}</span><strong>{withdrawal.owner_comment}</strong></div>}
    <div><span>ID</span><code>{withdrawal.id}</code></div>
  </div>;
}
