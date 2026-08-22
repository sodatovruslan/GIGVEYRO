"use client";

import { type FormEvent, useState } from "react";
import { useTranslations } from "next-intl";

import { useAppFormat } from "@/features/i18n/use-app-format";
import { useEnumLabels } from "@/features/i18n/use-enum-labels";
import { useLocalizedError } from "@/features/i18n/use-localized-error";
import { depositsApi } from "@/lib/api/deposits";
import type { Deposit, DepositStatus } from "@/lib/api/types";
import { useApiQuery } from "@/lib/hooks/use-api-query";

import styles from "./deposits-page.module.css";

const statuses: DepositStatus[] = ["waiting", "detected", "confirming", "confirmed", "credited", "expired", "failed", "amount_mismatch"];

export function DepositsPage({ owner }: { owner: boolean }) {
  const t = useTranslations("deposits");
  const common = useTranslations("common");
  const labels = useEnumLabels();
  const format = useAppFormat();
  const localizeError = useLocalizedError();
  const [status, setStatus] = useState<DepositStatus | "">("");
  const query = useApiQuery(() => depositsApi.list(owner, status || undefined), `deposits:${owner}:${status}`);
  const [modal, setModal] = useState(false);
  const [amount, setAmount] = useState("");
  const [created, setCreated] = useState<Deposit | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function create(event: FormEvent) { event.preventDefault(); setSaving(true); setError(""); try { const result = await depositsApi.create(amount); setCreated(result); setAmount(""); await query.refetch(); } catch (reason) { setError(localizeError(reason)); } finally { setSaving(false); } }
  function close() { setModal(false); setCreated(null); setError(""); }

  return <section><div className={styles.heading}><div><span>{owner ? t("eyebrowOwner") : t("eyebrowUser")}</span><h1>{t("title")}</h1><p>{owner ? t("ownerSubtitle") : t("userSubtitle")}</p></div>{!owner && <button onClick={() => setModal(true)}>＋ {t("create")}</button>}</div>
    <select className={styles.filter} aria-label={common("status")} value={status} onChange={(event) => setStatus(event.target.value as typeof status)}><option value="">{common("allStatuses")}</option>{statuses.map((value) => <option key={value} value={value}>{labels.deposit(value)}</option>)}</select>
    {error && <div className={styles.error}>{error}</div>}{query.error && <div className={styles.error}>{query.error}</div>}
    <div className={styles.card}>{query.loading ? <div className={styles.state}>{t("loading")}</div> : !query.data?.items.length ? <div className={styles.state}>{t("empty")}</div> : <div className={styles.table}><table><thead><tr><th>ID / {common("date")}</th>{owner && <th>{t("account")}</th>}<th>{t("expected")}</th><th>{t("receivedCredited")}</th><th>{t("confirmations")}</th><th>{common("status")}</th><th>{t("transaction")}</th></tr></thead><tbody>{query.data.items.map((item) => <tr key={item.id}><td><strong>{item.public_id}</strong><small>{format.dateTime(item.created_at)}</small></td>{owner && <td><code>{item.account_id}</code></td>}<td>{item.expected_amount} {item.asset}<small>{item.network}</small></td><td>{item.received_amount || "—"}<small>{t("credited", { amount: item.credited_amount || "—" })}</small></td><td>{item.confirmations} / {item.required_confirmations}</td><td><span className={`${styles.status} ${styles[item.status]}`}>{labels.deposit(item.status)}</span></td><td><code>{item.tx_hash ? shorten(item.tx_hash) : "—"}</code></td></tr>)}</tbody></table></div>}</div>
    {modal && <div className={styles.modalBackdrop} onMouseDown={close}><div className={styles.modal} onMouseDown={(event) => event.stopPropagation()}><h2>{created ? t("createdTitle") : t("createTitle")}</h2><p>{created ? t("createdText") : t("createText")}</p>{created ? <div className={styles.intent}><span>{common("amount")}</span><strong>{created.expected_amount} {created.asset}</strong><span>{common("network")}</span><b>{created.network}</b><span>{common("address")}</span><code>{created.deposit_address}</code><span>{common("validUntil")}</span><b>{format.dateTime(created.expires_at)}</b></div> : <form onSubmit={create}><label>{t("amountUsdt")}<input required type="number" min="0.00000001" step="0.00000001" value={amount} onChange={(event) => setAmount(event.target.value)} /></label>{error && <div className={styles.error}>{error}</div>}<div className={styles.actions}><button type="button" onClick={close}>{common("cancel")}</button><button disabled={saving}>{saving ? common("creating") : t("createAction")}</button></div></form>}{created && <div className={styles.actions}><button onClick={close}>{t("done")}</button></div>}</div></div>}
  </section>;
}

function shorten(value: string) { return value.length > 18 ? `${value.slice(0, 8)}…${value.slice(-7)}` : value; }
