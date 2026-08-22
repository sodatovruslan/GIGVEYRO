"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { useAppFormat } from "@/features/i18n/use-app-format";
import { useEnumLabels } from "@/features/i18n/use-enum-labels";
import { useLocalizedError } from "@/features/i18n/use-localized-error";
import { ownerOperationsApi } from "@/lib/api/owner-operations";
import type { MerchantWithdrawal } from "@/lib/api/types";
import { useApiQuery } from "@/lib/hooks/use-api-query";

import { Heading } from "../owner-components";
import styles from "../operations.module.css";

type Action = "approve" | "reject" | "mark-paid";
const statuses: MerchantWithdrawal["status"][] = ["pending", "approved", "paid", "rejected", "cancelled"];

export default function OwnerWithdrawalsPage() {
  const t = useTranslations("withdrawals");
  const common = useTranslations("common");
  const labels = useEnumLabels();
  const format = useAppFormat();
  const localizeError = useLocalizedError();
  const [status, setStatus] = useState<MerchantWithdrawal["status"] | "">("");
  const query = useApiQuery(() => ownerOperationsApi.withdrawals(status || undefined), `owner-withdrawals:${status}`);
  const [target, setTarget] = useState<{ item: MerchantWithdrawal; action: Action } | null>(null);
  const [comment, setComment] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function act() { if (!target) return; setSaving(true); setError(""); try { const value = comment || null; if (target.action === "approve") await ownerOperationsApi.approveWithdrawal(target.item.id, value); else if (target.action === "reject") await ownerOperationsApi.rejectWithdrawal(target.item.id, value); else await ownerOperationsApi.markWithdrawalPaid(target.item.id, value); setTarget(null); setComment(""); await query.refetch(); } catch (reason) { setError(localizeError(reason)); } finally { setSaving(false); } }
  const actionLabel = (action: Action) => action === "approve" ? t("approveTitle") : action === "reject" ? t("rejectTitle") : t("paidTitle");

  return <section><Heading title={t("ownerTitle")} text={t("ownerSubtitle")} />
    <div className={styles.toolbar}><select aria-label={common("status")} value={status} onChange={(event) => setStatus(event.target.value as typeof status)}><option value="">{common("allStatuses")}</option>{statuses.map((value) => <option value={value} key={value}>{labels.withdrawal(value)}</option>)}</select></div>
    {error && <div className={styles.error}>{error}</div>}{query.error && <div className={styles.error}>{query.error}</div>}
    <div className={styles.card}>{query.loading ? <div className={styles.state}>{t("loading")}</div> : !query.data?.items.length ? <div className={styles.state}>{t("notFound")}</div> : <div className={styles.table}><table><thead><tr><th>ID / {common("date")}</th><th>{t("merchant")}</th><th>{t("destination")}</th><th>{common("amount")}</th><th>{common("status")}</th><th>{common("actions")}</th></tr></thead><tbody>{query.data.items.map((item) => <tr key={item.id}><td><strong>{item.public_id}</strong><small>{format.dateTime(item.created_at)}</small></td><td><code>{item.merchant_id}</code></td><td>{labels.destination(item.destination_type)}<small>{item.destination}</small></td><td><strong>{item.amount} {item.currency.toUpperCase()}</strong></td><td><span className={`${styles.status} ${styles[item.status]}`}>{labels.withdrawal(item.status)}</span></td><td><div className={styles.actions}>{item.status === "pending" && <><button onClick={() => setTarget({ item, action: "approve" })}>{t("approve")}</button><button onClick={() => setTarget({ item, action: "reject" })}>{t("reject")}</button></>}{item.status === "approved" && <button onClick={() => setTarget({ item, action: "mark-paid" })}>{t("markPaid")}</button>}</div></td></tr>)}</tbody></table></div>}</div>
    {target && <div className={styles.modalBackdrop} onMouseDown={() => setTarget(null)}><div className={styles.modal} onMouseDown={(event) => event.stopPropagation()}><h2>{actionLabel(target.action)}</h2><p>{target.item.public_id} · {target.item.amount} {target.item.currency.toUpperCase()}</p><label>{t("ownerComment")}<textarea maxLength={500} value={comment} onChange={(event) => setComment(event.target.value)} /></label>{error && <div className={styles.error}>{error}</div>}<footer><button onClick={() => setTarget(null)}>{common("cancel")}</button><button disabled={saving} onClick={() => void act()}>{saving ? common("saving") : common("confirm")}</button></footer></div></div>}
  </section>;
}
