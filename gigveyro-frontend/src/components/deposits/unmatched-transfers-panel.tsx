"use client";

import { type FormEvent, useState } from "react";
import { useTranslations } from "next-intl";

import { Pager } from "@/components/ui/pager";
import { useAppFormat } from "@/features/i18n/use-app-format";
import { useLocalizedError } from "@/features/i18n/use-localized-error";
import { unmatchedTransfersApi, type UnmatchedTransferFilters } from "@/lib/api/deposits";
import { ApiError } from "@/lib/api/error";
import type { CorrelationStatus, ReconciliationStatus, UnmatchedTransferDetail } from "@/lib/api/types";
import { useApiQuery } from "@/lib/hooks/use-api-query";

import styles from "./unmatched-transfers-panel.module.css";

const PAGE_SIZE = 20;
const correlationStatuses: CorrelationStatus[] = ["UNMATCHED", "AMBIGUOUS", "MATCHED"];
const reconciliationStatuses: ReconciliationStatus[] = ["PENDING", "REPROCESSED", "IGNORED", "CREDITED"];
const emptyFilters: UnmatchedTransferFilters = {
  status: undefined, reconciliationStatus: undefined, txHash: "", reason: "", dateFrom: "", dateTo: "", minAmount: "", maxAmount: "",
};
type Confirmation = "link" | "reprocess" | "ignore" | null;

export function UnmatchedTransfersPanel() {
  const t = useTranslations("deposits");
  const common = useTranslations("common");
  const format = useAppFormat();
  const localizeError = useLocalizedError();
  const [draft, setDraft] = useState(emptyFilters);
  const [filters, setFilters] = useState(emptyFilters);
  const [offset, setOffset] = useState(0);
  const query = useApiQuery(
    () => unmatchedTransfersApi.list(filters, PAGE_SIZE, offset),
    `unmatched-transfers:${JSON.stringify(filters)}:${offset}`,
  );
  const [detail, setDetail] = useState<UnmatchedTransferDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [selectedDepositId, setSelectedDepositId] = useState("");
  const [ignoreReason, setIgnoreReason] = useState("");
  const [confirmation, setConfirmation] = useState<Confirmation>(null);
  const [mutationLoading, setMutationLoading] = useState(false);
  const [mutationError, setMutationError] = useState("");
  const [success, setSuccess] = useState("");

  function apply(event: FormEvent) { event.preventDefault(); setFilters(draft); setOffset(0); }
  function reset() { setDraft(emptyFilters); setFilters(emptyFilters); setOffset(0); }

  async function openDetail(id: string) {
    setDetail(null); setDetailError(""); setDetailLoading(true); setSelectedDepositId("");
    setIgnoreReason(""); setConfirmation(null); setMutationError("");
    try { setDetail(await unmatchedTransfersApi.get(id)); }
    catch (reason) { setDetailError(localizeError(reason)); }
    finally { setDetailLoading(false); }
  }

  function closeDetail() {
    if (mutationLoading) return;
    setDetail(null); setDetailError(""); setConfirmation(null);
  }

  function actionError(reason: unknown) {
    if (reason instanceof ApiError && reason.code) {
      const known = [
        "TRANSFER_NOT_FOUND", "DEPOSIT_NOT_FOUND", "IDEMPOTENCY_CONFLICT", "NETWORK_MISMATCH",
        "TOKEN_MISMATCH", "ADDRESS_MISMATCH", "TRANSFER_NOT_FINAL", "DEPOSIT_ALREADY_CREDITED",
        "DEPOSIT_EXPIRED", "STALE_STATE", "AMOUNT_MISMATCH", "TRANSFER_ALREADY_CREDITED",
        "TRANSFER_IGNORED", "TRANSFER_ALREADY_LINKED",
      ];
      if (known.includes(reason.code)) return t(`reconciliationErrors.${reason.code}`);
    }
    return localizeError(reason);
  }

  async function executeAction() {
    if (!detail || !confirmation) return;
    setMutationLoading(true); setMutationError("");
    try {
      const key = `owner-reconciliation-${crypto.randomUUID()}`;
      if (confirmation === "link") await unmatchedTransfersApi.link(detail.id, selectedDepositId, key);
      else if (confirmation === "reprocess") await unmatchedTransfersApi.reprocess(detail.id, key);
      else await unmatchedTransfersApi.ignore(detail.id, ignoreReason.trim(), key);
      setSuccess(t(`actionSuccess.${confirmation}`));
      setConfirmation(null);
      setDetail(await unmatchedTransfersApi.get(detail.id));
      await query.refetch();
      window.setTimeout(() => setSuccess(""), 3500);
    } catch (reason) { setMutationError(actionError(reason)); }
    finally { setMutationLoading(false); }
  }

  const selectedCandidate = detail?.candidates.find((candidate) => candidate.id === selectedDepositId);
  const actionable = detail && ["PENDING", "REPROCESSED"].includes(detail.reconciliation_status);
  const statusClass = (value: CorrelationStatus) => value === "UNMATCHED" ? styles.unmatched : value === "AMBIGUOUS" ? styles.ambiguous : styles.matched;

  return <section className={styles.section}>
    <h2>{t("unmatchedTitle")}</h2><p>{t("unmatchedSubtitle")}</p>
    <form className={styles.toolbar} onSubmit={apply}>
      <input aria-label={t("txHashPlaceholder")} placeholder={t("txHashPlaceholder")} value={draft.txHash} onChange={(event) => setDraft({ ...draft, txHash: event.target.value })} />
      <input aria-label={t("reason")} placeholder={t("reason")} value={draft.reason} onChange={(event) => setDraft({ ...draft, reason: event.target.value })} />
      <input aria-label={t("minAmount")} placeholder={t("minAmount")} type="number" min="0" step="0.00000001" value={draft.minAmount} onChange={(event) => setDraft({ ...draft, minAmount: event.target.value })} />
      <input aria-label={t("maxAmount")} placeholder={t("maxAmount")} type="number" min="0" step="0.00000001" value={draft.maxAmount} onChange={(event) => setDraft({ ...draft, maxAmount: event.target.value })} />
      <input aria-label={t("dateFrom")} type="date" value={draft.dateFrom} onChange={(event) => setDraft({ ...draft, dateFrom: event.target.value })} />
      <input aria-label={t("dateTo")} type="date" value={draft.dateTo} onChange={(event) => setDraft({ ...draft, dateTo: event.target.value })} />
      <select aria-label={t("correlationStatus")} value={draft.status ?? ""} onChange={(event) => setDraft({ ...draft, status: (event.target.value || undefined) as CorrelationStatus | undefined })}>
        <option value="">{common("allStatuses")}</option>{correlationStatuses.map((value) => <option key={value} value={value}>{t(`correlation.${value}`)}</option>)}
      </select>
      <select aria-label={t("reconciliationStatus")} value={draft.reconciliationStatus ?? ""} onChange={(event) => setDraft({ ...draft, reconciliationStatus: (event.target.value || undefined) as ReconciliationStatus | undefined })}>
        <option value="">{common("allStatuses")}</option>{reconciliationStatuses.map((value) => <option key={value} value={value}>{t(`reconciliation.${value}`)}</option>)}
      </select>
      <button>{t("apply")}</button><button type="button" className={styles.secondary} onClick={reset}>{t("reset")}</button>
    </form>
    {query.error && <div className={styles.error}>{query.error}</div>}
    <div className={styles.card}>
      {query.loading ? <div className={styles.state}>{t("loading")}</div> : !query.data?.items.length ? <div className={styles.state}>{t("unmatchedEmpty")}</div> : <div className={styles.table}><table><thead><tr>
        <th>{common("date")}</th><th>{t("transaction")}</th><th>{common("amount")}</th><th>{t("correlationStatus")}</th><th>{t("reconciliationStatus")}</th><th>{t("reason")}</th>
      </tr></thead><tbody>{query.data.items.map((item) => <tr key={item.id} className={styles.row} onClick={() => openDetail(item.id)}>
        <td>{format.dateTime(item.created_at)}</td><td><code>{shorten(item.tx_hash)}</code></td><td>{item.amount} USDT</td>
        <td><span className={`${styles.status} ${statusClass(item.correlation_status)}`}>{t(`correlation.${item.correlation_status}`)}</span></td>
        <td><span className={styles.status}>{t(`reconciliation.${item.reconciliation_status}`)}</span></td><td>{item.reason}</td>
      </tr>)}</tbody></table></div>}
      {query.data && <Pager offset={offset} limit={PAGE_SIZE} itemCount={query.data.items.length} total={query.data.total} onPage={setOffset} />}
    </div>
    {success && <div className={styles.toast} role="status">{success}</div>}
    {(detailLoading || detail || detailError) && <div className={styles.modalBackdrop} onMouseDown={closeDetail}><div className={styles.modal} onMouseDown={(event) => event.stopPropagation()}>
      <h2>{t("unmatchedDetailTitle")}</h2>
      {detailLoading ? <p>{t("loading")}</p> : detailError ? <div className={styles.error}>{detailError}</div> : detail && <>
        <div className={styles.intent}>
          <span>{t("correlationStatus")}</span><b>{t(`correlation.${detail.correlation_status}`)}</b><span>{t("reconciliationStatus")}</span><b>{t(`reconciliation.${detail.reconciliation_status}`)}</b>
          <span>{t("reason")}</span><b>{detail.reason}</b><span>{common("amount")}</span><b>{detail.amount} USDT</b>
          <span>{t("network")}</span><b>{detail.network}</b><span>{t("finality")}</span><b>{detail.is_finalized ? t("finalized") : t("notFinalized")} · {detail.confirmations}</b>
          <span>{t("fromAddress")}</span><code>{detail.from_address}</code><span>{t("toAddress")}</span><code>{detail.to_address}</code>
          <span>{t("transaction")}</span><code>{detail.tx_hash}</code><span>{common("date")}</span><b>{format.dateTime(detail.block_timestamp ?? detail.created_at)}</b>
        </div>
        <h3 className={styles.subheading}>{t("candidateTitle")}</h3>
        {!detail.candidates.length ? <p className={styles.muted}>{t("candidateEmpty")}</p> : <div className={styles.candidates}>{detail.candidates.map((candidate) => <label key={candidate.id} className={styles.candidate}>
          <input type="radio" name="candidate" value={candidate.id} checked={selectedDepositId === candidate.id} disabled={!candidate.amount_matches || !actionable} onChange={() => setSelectedDepositId(candidate.id)} />
          <span><b>{candidate.public_id}</b><small>{candidate.expected_amount} USDT · {candidate.network} · {format.dateTime(candidate.expires_at)}</small></span>
          <em className={candidate.amount_matches ? styles.match : styles.mismatch}>{candidate.amount_matches ? t("amountMatch") : t("amountMismatch")}</em>
        </label>)}</div>}
        {actionable && <div className={styles.workflow}>
          <button disabled={!selectedDepositId} onClick={() => setConfirmation("link")}>{t("linkAction")}</button><button className={styles.secondaryAction} onClick={() => setConfirmation("reprocess")}>{t("reprocessAction")}</button>
          <textarea aria-label={t("ignoreReason")} placeholder={t("ignoreReason")} value={ignoreReason} maxLength={500} onChange={(event) => setIgnoreReason(event.target.value)} />
          <button className={styles.dangerAction} disabled={ignoreReason.trim().length < 5} onClick={() => setConfirmation("ignore")}>{t("ignoreAction")}</button>
        </div>}
        {confirmation && <div className={styles.confirmation} role="alertdialog">
          <b>{t(`confirmation.${confirmation}.title`)}</b><p>{t(`confirmation.${confirmation}.text`)}</p>
          {confirmation === "link" && selectedCandidate && <dl><dt>{t("observedAmount")}</dt><dd>{detail.amount} USDT</dd><dt>{t("expectedAmount")}</dt><dd>{selectedCandidate.expected_amount} USDT</dd><dt>{t("amountDifference")}</dt><dd>{selectedCandidate.amount_difference} USDT</dd><dt>{t("network")}</dt><dd>{detail.network}</dd><dt>{t("expiresAt")}</dt><dd>{format.dateTime(selectedCandidate.expires_at)}</dd></dl>}
          {confirmation === "ignore" && <p className={styles.warning}>{t("ignoreWarning")}</p>}
          <div className={styles.actions}><button className={styles.secondaryAction} disabled={mutationLoading} onClick={() => setConfirmation(null)}>{t("cancel")}</button><button disabled={mutationLoading} onClick={executeAction}>{mutationLoading ? t("processing") : t("confirmAction")}</button></div>
        </div>}
        {mutationError && <div className={styles.error}>{mutationError}</div>}
        {!!detail.history.length && <><h3 className={styles.subheading}>{t("historyTitle")}</h3><div className={styles.history}>{detail.history.map((item) => <p key={item.id}><b>{t(`actions.${item.action}`)}</b><span>{item.result_code} · {format.dateTime(item.created_at)}</span></p>)}</div></>}
      </>}
      <div className={styles.actions}><button className={styles.secondaryAction} disabled={mutationLoading} onClick={closeDetail}>{t("done")}</button></div>
    </div></div>}
  </section>;
}

function shorten(value: string) { return value.length > 18 ? `${value.slice(0, 8)}…${value.slice(-7)}` : value; }
