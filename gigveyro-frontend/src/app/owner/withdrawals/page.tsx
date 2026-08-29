"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { useAppFormat } from "@/features/i18n/use-app-format";
import { useEnumLabels } from "@/features/i18n/use-enum-labels";
import { useLocalizedError } from "@/features/i18n/use-localized-error";
import { isWithdrawalStateConflict } from "@/features/withdrawals/validation";
import { ownerOperationsApi } from "@/lib/api/owner-operations";
import type { MerchantWithdrawal } from "@/lib/api/types";
import { useApiQuery } from "@/lib/hooks/use-api-query";
import { Pager } from "@/components/ui/pager";
import { WithdrawalDetailGrid } from "@/components/withdrawals/withdrawal-detail";

import { Heading } from "../owner-components";
import styles from "../operations.module.css";

const PAGE_SIZE = 20;
type Action = "approve" | "reject";
const statuses: MerchantWithdrawal["status"][] = ["pending", "approved", "paid", "rejected", "cancelled"];

export default function OwnerWithdrawalsPage() {
  const t = useTranslations("withdrawals");
  const common = useTranslations("common");
  const labels = useEnumLabels();
  const format = useAppFormat();
  const localizeError = useLocalizedError();
  const [status, setStatus] = useState<MerchantWithdrawal["status"] | "">("");
  const [offset, setOffset] = useState(0);
  const query = useApiQuery(() => ownerOperationsApi.withdrawals(status || undefined, PAGE_SIZE, offset), `owner-withdrawals:${status}:${offset}`);
  function changeStatus(value: MerchantWithdrawal["status"] | "") { setStatus(value); setOffset(0); }
  const [target, setTarget] = useState<{ item: MerchantWithdrawal; action: Action } | null>(null);
  const [comment, setComment] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [detail, setDetail] = useState<MerchantWithdrawal | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");

  async function openDetail(id: string) {
    setDetail(null); setDetailError(""); setDetailLoading(true);
    try { setDetail(await ownerOperationsApi.getWithdrawal(id)); }
    catch (reason) { setDetailError(localizeError(reason)); }
    finally { setDetailLoading(false); }
  }
  function closeDetail() { setDetail(null); setDetailError(""); }

  async function act() {
    if (!target) return;
    setSaving(true); setError("");
    try {
      const value = comment || null;
      if (target.action === "approve") await ownerOperationsApi.approveWithdrawal(target.item.id, value);
      else await ownerOperationsApi.rejectWithdrawal(target.item.id, value);
      setTarget(null); setComment(""); await query.refetch();
    } catch (reason) {
      if (isWithdrawalStateConflict(reason)) { setTarget(null); setError(t("staleStateError")); }
      else setError(localizeError(reason));
      await query.refetch();
    } finally { setSaving(false); }
  }
  const actionLabel = (action: Action) => action === "approve" ? t("approveTitle") : t("rejectTitle");

  return <section><Heading title={t("ownerTitle")} text={t("ownerSubtitle")} />
    <div className={styles.toolbar}><select aria-label={common("status")} value={status} onChange={(event) => changeStatus(event.target.value as typeof status)}><option value="">{common("allStatuses")}</option>{statuses.map((value) => <option value={value} key={value}>{labels.withdrawal(value)}</option>)}</select></div>
    {error && <div className={styles.error}>{error}</div>}{query.error && <div className={styles.error}>{query.error}</div>}
    <div className={styles.card}>{query.loading ? <div className={styles.state}>{t("loading")}</div> : !query.data?.items.length ? <div className={styles.state}>{t("notFound")}</div> : <div className={styles.table}><table><thead><tr><th>ID / {common("date")}</th><th>{t("merchant")}</th><th>{t("destination")}</th><th>{common("amount")}</th><th>{common("status")}</th><th>{common("actions")}</th></tr></thead><tbody>{query.data.items.map((item) => <tr key={item.id} className={styles.row} onClick={() => void openDetail(item.id)}><td><strong>{item.public_id}</strong><small>{format.dateTime(item.created_at)}</small></td><td><code>{item.merchant_id}</code></td><td>{labels.destination(item.destination_type)}<small>{item.destination}</small></td><td><strong>{item.amount} {item.currency.toUpperCase()}</strong></td><td><span className={`${styles.status} ${styles[item.status]}`}>{labels.withdrawal(item.status)}</span></td><td onClick={(event) => event.stopPropagation()}><div className={styles.actions}>{item.status === "pending" && <><button onClick={() => setTarget({ item, action: "approve" })}>{t("approve")}</button><button onClick={() => setTarget({ item, action: "reject" })}>{t("reject")}</button></>}</div></td></tr>)}</tbody></table></div>}
      {query.data && <Pager offset={offset} limit={PAGE_SIZE} itemCount={query.data.items.length} total={query.data.total} onPage={setOffset} />}
    </div>
    {target && <div className={styles.modalBackdrop} onMouseDown={() => setTarget(null)}><div className={styles.modal} onMouseDown={(event) => event.stopPropagation()}><h2>{actionLabel(target.action)}</h2><p>{target.item.public_id} · {target.item.amount} {target.item.currency.toUpperCase()}</p><label>{t("ownerComment")}<textarea maxLength={500} value={comment} onChange={(event) => setComment(event.target.value)} /></label>{error && <div className={styles.error}>{error}</div>}<footer><button onClick={() => setTarget(null)}>{common("cancel")}</button><button disabled={saving} onClick={() => void act()}>{saving ? common("saving") : common("confirm")}</button></footer></div></div>}
    {(detailLoading || detail || detailError) && <div className={styles.modalBackdrop} onMouseDown={closeDetail}><div className={styles.modal} onMouseDown={(event) => event.stopPropagation()}><h2>{t("detailTitle")}</h2>{detailLoading ? <p>{t("loading")}</p> : detailError ? <div className={styles.error}>{detailError}</div> : detail && <WithdrawalDetailGrid withdrawal={detail} owner />}<footer><button onClick={closeDetail}>{common("cancel")}</button></footer></div></div>}
  </section>;
}
