"use client";

import { type FormEvent, useState } from "react";
import { useTranslations } from "next-intl";

import { useAppFormat } from "@/features/i18n/use-app-format";
import { useLocalizedError } from "@/features/i18n/use-localized-error";
import { unmatchedTransfersApi, type UnmatchedTransferFilters } from "@/lib/api/deposits";
import type { CorrelationStatus, UnmatchedTransfer } from "@/lib/api/types";
import { useApiQuery } from "@/lib/hooks/use-api-query";
import { Pager } from "@/components/ui/pager";

import styles from "./unmatched-transfers-panel.module.css";

const PAGE_SIZE = 20;
const statuses: CorrelationStatus[] = ["UNMATCHED", "AMBIGUOUS", "MATCHED"];
const emptyFilters: UnmatchedTransferFilters = { status: undefined, txHash: "", dateFrom: "", dateTo: "", minAmount: "", maxAmount: "" };

export function UnmatchedTransfersPanel() {
  const t = useTranslations("deposits");
  const common = useTranslations("common");
  const format = useAppFormat();
  const localizeError = useLocalizedError();
  const [draft, setDraft] = useState(emptyFilters);
  const [filters, setFilters] = useState(emptyFilters);
  const [offset, setOffset] = useState(0);
  const query = useApiQuery(() => unmatchedTransfersApi.list(filters, PAGE_SIZE, offset), `unmatched-transfers:${JSON.stringify(filters)}:${offset}`);
  const [detail, setDetail] = useState<UnmatchedTransfer | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");

  function apply(event: FormEvent) { event.preventDefault(); setFilters(draft); setOffset(0); }
  function reset() { setDraft(emptyFilters); setFilters(emptyFilters); setOffset(0); }
  async function openDetail(id: string) { setDetail(null); setDetailError(""); setDetailLoading(true); try { setDetail(await unmatchedTransfersApi.get(id)); } catch (reason) { setDetailError(localizeError(reason)); } finally { setDetailLoading(false); } }
  function closeDetail() { setDetail(null); setDetailError(""); }
  const statusClass = (value: CorrelationStatus) => value === "UNMATCHED" ? styles.unmatched : value === "AMBIGUOUS" ? styles.ambiguous : styles.matched;

  return <section className={styles.section}>
    <h2>{t("unmatchedTitle")}</h2>
    <p>{t("unmatchedSubtitle")}</p>
    <form className={styles.toolbar} onSubmit={apply}>
      <input aria-label={t("txHashPlaceholder")} placeholder={t("txHashPlaceholder")} value={draft.txHash} onChange={(event) => setDraft({ ...draft, txHash: event.target.value })} />
      <input aria-label={t("minAmount")} placeholder={t("minAmount")} type="number" min="0" step="0.00000001" value={draft.minAmount} onChange={(event) => setDraft({ ...draft, minAmount: event.target.value })} />
      <input aria-label={t("maxAmount")} placeholder={t("maxAmount")} type="number" min="0" step="0.00000001" value={draft.maxAmount} onChange={(event) => setDraft({ ...draft, maxAmount: event.target.value })} />
      <input aria-label={t("dateFrom")} type="date" value={draft.dateFrom} onChange={(event) => setDraft({ ...draft, dateFrom: event.target.value })} />
      <input aria-label={t("dateTo")} type="date" value={draft.dateTo} onChange={(event) => setDraft({ ...draft, dateTo: event.target.value })} />
      <select aria-label={common("status")} value={draft.status ?? ""} onChange={(event) => setDraft({ ...draft, status: (event.target.value || undefined) as CorrelationStatus | undefined })}>
        <option value="">{common("allStatuses")}</option>
        {statuses.map((value) => <option key={value} value={value}>{t(`correlation.${value}`)}</option>)}
      </select>
      <button>{t("apply")}</button>
      <button type="button" className={styles.secondary} onClick={reset}>{t("reset")}</button>
    </form>
    {query.error && <div className={styles.error}>{query.error}</div>}
    <div className={styles.card}>
      {query.loading ? <div className={styles.state}>{t("loading")}</div> : !query.data?.items.length ? <div className={styles.state}>{t("unmatchedEmpty")}</div> : <div className={styles.table}><table><thead><tr>
        <th>{common("date")}</th><th>{t("transaction")}</th><th>{common("amount")}</th><th>{common("status")}</th><th>{t("reason")}</th>
      </tr></thead><tbody>{query.data.items.map((item) => <tr key={item.id} className={styles.row} onClick={() => openDetail(item.id)}>
        <td>{format.dateTime(item.created_at)}</td>
        <td><code>{shorten(item.tx_hash)}</code></td>
        <td>{item.amount}</td>
        <td><span className={`${styles.status} ${statusClass(item.correlation_status)}`}>{t(`correlation.${item.correlation_status}`)}</span></td>
        <td>{item.reason}</td>
      </tr>)}</tbody></table></div>}
      {query.data && <Pager offset={offset} limit={PAGE_SIZE} itemCount={query.data.items.length} total={query.data.total} onPage={setOffset} />}
    </div>
    {(detailLoading || detail || detailError) && <div className={styles.modalBackdrop} onMouseDown={closeDetail}><div className={styles.modal} onMouseDown={(event) => event.stopPropagation()}>
      <h2>{t("unmatchedDetailTitle")}</h2>
      {detailLoading ? <p>{t("loading")}</p> : detailError ? <div className={styles.error}>{detailError}</div> : detail && <div className={styles.intent}>
        <span>{common("status")}</span><span className={`${styles.status} ${statusClass(detail.correlation_status)}`}>{t(`correlation.${detail.correlation_status}`)}</span>
        <span>{t("reason")}</span><b>{detail.reason}</b>
        <span>{common("amount")}</span><b>{detail.amount}</b>
        <span>{t("fromAddress")}</span><code>{detail.from_address}</code>
        <span>{t("toAddress")}</span><code>{detail.to_address}</code>
        <span>{t("transaction")}</span><code>{detail.tx_hash}</code>
        <span>{common("date")}</span><b>{format.dateTime(detail.created_at)}</b>
      </div>}
      <div className={styles.actions}><button onClick={closeDetail}>{t("done")}</button></div>
    </div></div>}
  </section>;
}

function shorten(value: string) { return value.length > 18 ? `${value.slice(0, 8)}…${value.slice(-7)}` : value; }
