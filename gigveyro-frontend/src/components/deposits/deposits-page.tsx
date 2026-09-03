"use client";

import { type FormEvent, type KeyboardEvent, useState } from "react";
import { useTranslations } from "next-intl";

import { Pager } from "@/components/ui/pager";
import { useAppFormat } from "@/features/i18n/use-app-format";
import { useEnumLabels } from "@/features/i18n/use-enum-labels";
import { useLocalizedError } from "@/features/i18n/use-localized-error";
import { depositsApi, type DepositOwnerFilters } from "@/lib/api/deposits";
import type { Deposit, DepositStatus } from "@/lib/api/types";
import { useApiQuery } from "@/lib/hooks/use-api-query";

import { UnmatchedTransfersPanel } from "./unmatched-transfers-panel";
import styles from "./deposits-page.module.css";

const PAGE_SIZE = 20;
const statuses: DepositStatus[] = [
  "waiting", "detected", "confirming", "confirmed", "credited", "expired", "failed",
  "amount_mismatch",
];
const emptyOwnerFilters: DepositOwnerFilters = {
  search: "", txHash: "", dateFrom: "", dateTo: "",
};

export function DepositsPage({ owner }: { owner: boolean }) {
  const t = useTranslations("deposits");
  const common = useTranslations("common");
  const labels = useEnumLabels();
  const format = useAppFormat();
  const localizeError = useLocalizedError();
  const [status, setStatus] = useState<DepositStatus | "">("");
  const [draft, setDraft] = useState(emptyOwnerFilters);
  const [ownerFilters, setOwnerFilters] = useState(emptyOwnerFilters);
  const [offset, setOffset] = useState(0);
  const query = useApiQuery(
    () => depositsApi.list(owner, status || undefined, ownerFilters, PAGE_SIZE, offset),
    `deposits:${owner}:${status}:${JSON.stringify(ownerFilters)}:${offset}`,
  );
  const [modal, setModal] = useState(false);
  const [amount, setAmount] = useState("");
  const [created, setCreated] = useState<Deposit | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [detail, setDetail] = useState<Deposit | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [copyError, setCopyError] = useState("");
  const [copied, setCopied] = useState(false);

  async function create(event: FormEvent) {
    event.preventDefault(); setSaving(true); setError("");
    try {
      const result = await depositsApi.create(amount);
      setCreated(result); setAmount(""); await query.refetch();
    } catch (reason) { setError(localizeError(reason)); }
    finally { setSaving(false); }
  }
  function close() { setModal(false); setCreated(null); setError(""); }
  function applyFilters(event: FormEvent) {
    event.preventDefault(); setOwnerFilters(draft); setOffset(0);
  }
  function resetFilters() {
    setDraft(emptyOwnerFilters); setOwnerFilters(emptyOwnerFilters); setOffset(0);
  }
  function changeStatus(value: DepositStatus | "") { setStatus(value); setOffset(0); }
  async function openDetail(id: string) {
    setDetail(null); setDetailError(""); setCopyError(""); setDetailLoading(true); setCopied(false);
    try { setDetail(await depositsApi.get(owner, id)); }
    catch (reason) { setDetailError(localizeError(reason)); }
    finally { setDetailLoading(false); }
  }
  function closeDetail() { setDetail(null); setDetailError(""); setCopyError(""); setCopied(false); }
  function openFromKeyboard(event: KeyboardEvent<HTMLTableRowElement>, id: string) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault(); void openDetail(id);
    }
  }
  async function copyAddress(address: string) {
    setCopyError("");
    try { await navigator.clipboard.writeText(address); setCopied(true); }
    catch { setCopyError(t("copyFailed")); }
  }

  return <section>
    <div className={styles.heading}>
      <div><span>{owner ? t("eyebrowOwner") : t("eyebrowUser")}</span><h1>{t("title")}</h1><p>{owner ? t("ownerSubtitle") : t("userSubtitle")}</p></div>
      {!owner && <button onClick={() => setModal(true)}>+ {t("create")}</button>}
    </div>
    {owner ? <form className={styles.toolbar} onSubmit={applyFilters}>
      <input aria-label={t("searchPlaceholder")} placeholder={t("searchPlaceholder")} value={draft.search} onChange={(event) => setDraft({ ...draft, search: event.target.value })} />
      <input aria-label={t("txHashPlaceholder")} placeholder={t("txHashPlaceholder")} value={draft.txHash} onChange={(event) => setDraft({ ...draft, txHash: event.target.value })} />
      <input aria-label={t("dateFrom")} type="date" value={draft.dateFrom} onChange={(event) => setDraft({ ...draft, dateFrom: event.target.value })} />
      <input aria-label={t("dateTo")} type="date" value={draft.dateTo} onChange={(event) => setDraft({ ...draft, dateTo: event.target.value })} />
      <select aria-label={common("status")} value={status} onChange={(event) => changeStatus(event.target.value as typeof status)}><option value="">{common("allStatuses")}</option>{statuses.map((value) => <option key={value} value={value}>{labels.deposit(value)}</option>)}</select>
      <button>{t("apply")}</button><button type="button" className={styles.secondary} onClick={resetFilters}>{t("reset")}</button>
    </form> : <select className={styles.filter} aria-label={common("status")} value={status} onChange={(event) => changeStatus(event.target.value as typeof status)}><option value="">{common("allStatuses")}</option>{statuses.map((value) => <option key={value} value={value}>{labels.deposit(value)}</option>)}</select>}
    {error && <div className={styles.error}>{error}</div>}{query.error && <div className={styles.error}>{query.error}</div>}
    <div className={styles.card}>
      {query.loading ? <div className={styles.state}>{t("loading")}</div> : !query.data?.items.length ? <div className={styles.state}>{t("empty")}</div> : <div className={styles.table}><table>
        <thead><tr><th>ID / {common("date")}</th>{owner && <th>{t("account")}</th>}<th>{t("expected")}</th><th>{t("receivedCredited")}</th><th>{t("confirmations")}</th><th>{common("status")}</th><th>{t("transaction")}</th></tr></thead>
        <tbody>{query.data.items.map((item) => <tr key={item.id} className={styles.row} tabIndex={0} onClick={() => void openDetail(item.id)} onKeyDown={(event) => openFromKeyboard(event, item.id)}>
          <td><strong>{item.public_id}</strong><small>{format.dateTime(item.created_at)}</small></td>{owner && <td><code>{item.account_id}</code></td>}<td>{item.expected_amount} {item.asset}<small>{item.network}</small></td><td>{item.received_amount || "—"}<small>{t("credited", { amount: item.credited_amount || "—" })}</small></td><td>{item.confirmations} / {item.required_confirmations}</td><td><span className={`${styles.status} ${styles[item.status]}`}>{labels.deposit(item.status)}</span></td><td><code>{item.tx_hash ? shorten(item.tx_hash) : "—"}</code></td>
        </tr>)}</tbody>
      </table></div>}
      {query.data && <Pager offset={offset} limit={PAGE_SIZE} itemCount={query.data.items.length} total={query.data.total} onPage={setOffset} />}
    </div>
    {owner && <UnmatchedTransfersPanel />}
    {modal && <div className={styles.modalBackdrop} onMouseDown={close}><div className={styles.modal} onMouseDown={(event) => event.stopPropagation()}>
      <h2>{created ? t("createdTitle") : t("createTitle")}</h2><p>{created ? t("createdText") : t("createText")}</p>
      {created ? <div className={styles.intent}><span>{common("amount")}</span><strong>{created.expected_amount} {created.asset}</strong><span>{common("network")}</span><b>{created.network}</b><span>{common("address")}</span><code>{created.deposit_address}</code><span>{common("validUntil")}</span><b>{format.dateTime(created.expires_at)}</b></div> : <form onSubmit={create}><label>{t("amountUsdt")}<input required type="number" min="0.00000001" step="0.00000001" value={amount} onChange={(event) => setAmount(event.target.value)} /></label>{error && <div className={styles.error}>{error}</div>}<div className={styles.actions}><button type="button" onClick={close}>{common("cancel")}</button><button disabled={saving}>{saving ? common("creating") : t("createAction")}</button></div></form>}
      {created && <div className={styles.actions}><button onClick={close}>{t("done")}</button></div>}
    </div></div>}
    {(detailLoading || detail || detailError) && <div className={styles.modalBackdrop} onMouseDown={closeDetail}><div className={styles.modal} onMouseDown={(event) => event.stopPropagation()}>
      <h2>{t("detailTitle")}</h2>
      {detailLoading ? <p>{t("loading")}</p> : detailError ? <div className={styles.error}>{detailError}</div> : detail && <div className={styles.intent}>
        {detail.status === "expired" && <p className={styles.expiredNotice}>{t("expiredNotice")}</p>}
        <span>{t("depositId")}</span><strong>{detail.public_id}</strong><span>{common("status")}</span><span className={`${styles.status} ${styles[detail.status]}`}>{labels.deposit(detail.status)}</span>{owner && <><span>{t("account")}</span><code>{detail.account_id}</code></>}<span>{t("expected")}</span><b>{detail.expected_amount} {detail.asset}</b><span>{common("network")}</span><b>{detail.network} · {detail.asset}</b><span>{t("receivedCredited")}</span><b>{detail.received_amount || "—"} / {detail.credited_amount || "—"}</b><span>{t("confirmations")}</span><b>{detail.confirmations} / {detail.required_confirmations}</b><span>{t("depositAddress")}</span><code>{detail.deposit_address}</code><button type="button" className={styles.copyButton} onClick={() => void copyAddress(detail.deposit_address)}>{copied ? t("copied") : t("copyAddress")}</button>{copyError && <p className={styles.copyError}>{copyError}</p>}<span>{t("transaction")}</span><code>{detail.tx_hash || "—"}</code><span>{t("expiresAt")}</span><b>{format.dateTime(detail.expires_at)}</b>
      </div>}
      <div className={styles.actions}><button onClick={closeDetail}>{t("done")}</button></div>
    </div></div>}
  </section>;
}

function shorten(value: string) {
  return value.length > 18 ? `${value.slice(0, 8)}…${value.slice(-7)}` : value;
}
