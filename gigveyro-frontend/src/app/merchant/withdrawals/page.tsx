"use client";

import { type FormEvent, useState } from "react";
import { useTranslations } from "next-intl";

import { PageHeading } from "@/app/user/user-components";
import { useAppFormat } from "@/features/i18n/use-app-format";
import { useEnumLabels } from "@/features/i18n/use-enum-labels";
import { useLocalizedError } from "@/features/i18n/use-localized-error";
import { isWithdrawalStateConflict, mapWithdrawalFieldErrors, type WithdrawalFieldErrors } from "@/features/withdrawals/validation";
import { merchantApi } from "@/lib/api/merchant";
import type { MerchantWithdrawal } from "@/lib/api/types";
import { useApiQuery } from "@/lib/hooks/use-api-query";
import { Pager } from "@/components/ui/pager";
import { WithdrawalDetailGrid } from "@/components/withdrawals/withdrawal-detail";

import styles from "../../user/user.module.css";

const PAGE_SIZE = 20;

export default function MerchantWithdrawalsPage() {
  const t = useTranslations("withdrawals");
  const common = useTranslations("common");
  const labels = useEnumLabels();
  const format = useAppFormat();
  const localizeError = useLocalizedError();
  const [offset, setOffset] = useState(0);
  const query = useApiQuery(() => merchantApi.withdrawals(undefined, PAGE_SIZE, offset), `merchant-withdrawals:${offset}`);
  const [modal, setModal] = useState(false);
  const [amount, setAmount] = useState("");
  const [destinationType, setDestinationType] = useState<MerchantWithdrawal["destination_type"]>("usdt_trc20_address");
  const [destination, setDestination] = useState("");
  const [comment, setComment] = useState("");
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<WithdrawalFieldErrors>({});
  const [saving, setSaving] = useState(false);
  const [detail, setDetail] = useState<MerchantWithdrawal | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");

  async function openDetail(id: string) {
    setDetail(null); setDetailError(""); setDetailLoading(true);
    try { setDetail(await merchantApi.getWithdrawal(id)); }
    catch (reason) { setDetailError(localizeError(reason)); }
    finally { setDetailLoading(false); }
  }
  function closeDetail() { setDetail(null); setDetailError(""); }

  async function create(event: FormEvent) {
    event.preventDefault(); setSaving(true); setError(""); setFieldErrors({});
    try { await merchantApi.createWithdrawal({ amount, destination_type: destinationType, destination, comment: comment || null }); setModal(false); setAmount(""); setDestination(""); setComment(""); await query.refetch(); }
    catch (reason) { const mapped = mapWithdrawalFieldErrors(reason, { invalidAmount: t("validation.amount"), invalidDestination: t("validation.destination"), invalidTrc20: t("validation.trc20"), invalidComment: t("validation.comment") }); setFieldErrors(mapped); if (!Object.keys(mapped).length) setError(localizeError(reason)); }
    finally { setSaving(false); }
  }

  async function cancel(id: string) {
    setError("");
    try { await merchantApi.cancelWithdrawal(id); await query.refetch(); }
    catch (reason) {
      setError(isWithdrawalStateConflict(reason) ? t("staleStateError") : localizeError(reason));
      await query.refetch();
    }
  }

  return <section><div className={styles.contentHeader} style={{ padding: 0, border: 0, marginBottom: 27 }}><PageHeading eyebrow={t("eyebrow")} title={t("merchantTitle")} text={t("merchantSubtitle")} /><button onClick={() => setModal(true)}>＋ {t("create")}</button></div>
    {error && <div className={styles.inlineError}>{error}</div>}
    <div className={styles.contentCard}>{query.loading ? <div className={styles.state}>{t("loading")}</div> : query.error ? <div className={`${styles.state} ${styles.errorText}`}>{query.error}</div> : !query.data?.items.length ? <div className={styles.state}>{t("empty")}</div> : <div className={styles.tableScroll}><table><thead><tr><th>ID</th><th>{common("date")}</th><th>{t("destination")}</th><th>{common("amount")}</th><th>{common("status")}</th><th /></tr></thead><tbody>{query.data.items.map((item) => <tr key={item.id} className={styles.row} onClick={() => void openDetail(item.id)}><td>{item.public_id}</td><td>{format.dateTime(item.created_at)}</td><td>{labels.destination(item.destination_type)}<br />{item.destination}</td><td>{item.amount} {item.currency.toUpperCase()}</td><td>{labels.withdrawal(item.status)}</td><td onClick={(event) => event.stopPropagation()}>{item.status === "pending" && <button className={styles.negative} onClick={() => void cancel(item.id)}>{t("cancelAction")}</button>}</td></tr>)}</tbody></table></div>}
      {query.data && <Pager offset={offset} limit={PAGE_SIZE} itemCount={query.data.items.length} total={query.data.total} onPage={setOffset} />}
    </div>
    {modal && <div className={styles.modalBackdrop} onMouseDown={() => setModal(false)}><div className={styles.modal} onMouseDown={(event) => event.stopPropagation()}><div className={styles.modalHeader}><h2>{t("newTitle")}</h2><button onClick={() => setModal(false)} aria-label={common("cancel")}>×</button></div><form className={styles.form} onSubmit={create}><label>{common("amount")} USDT<input aria-invalid={Boolean(fieldErrors.amount)} required type="number" min="0.00000001" step="0.00000001" value={amount} onChange={(event) => { setAmount(event.target.value); setFieldErrors((value) => ({ ...value, amount: undefined })); }} />{fieldErrors.amount && <span className={styles.formError}>{fieldErrors.amount}</span>}</label><label>{t("destinationType")}<select value={destinationType} onChange={(event) => { setDestinationType(event.target.value as MerchantWithdrawal["destination_type"]); setFieldErrors((value) => ({ ...value, destination_type: undefined, destination: undefined })); }}><option value="usdt_trc20_address">{labels.destination("usdt_trc20_address")}</option><option value="bybit_uid">{labels.destination("bybit_uid")}</option></select></label><label>{destinationType === "bybit_uid" ? "Bybit UID" : t("trc20Address")}<input aria-invalid={Boolean(fieldErrors.destination)} required minLength={3} maxLength={255} value={destination} onChange={(event) => { setDestination(event.target.value); setFieldErrors((value) => ({ ...value, destination: undefined })); }} />{fieldErrors.destination && <span className={styles.formError}>{fieldErrors.destination}</span>}</label><label>{t("comment")}<input aria-invalid={Boolean(fieldErrors.comment)} maxLength={500} value={comment} onChange={(event) => { setComment(event.target.value); setFieldErrors((value) => ({ ...value, comment: undefined })); }} />{fieldErrors.comment && <span className={styles.formError}>{fieldErrors.comment}</span>}</label>{error && <div className={styles.formError}>{error}</div>}<div className={styles.formActions}><button type="button" onClick={() => setModal(false)}>{common("cancel")}</button><button disabled={saving}>{saving ? common("creating") : common("create")}</button></div></form></div></div>}
    {(detailLoading || detail || detailError) && <div className={styles.modalBackdrop} onMouseDown={closeDetail}><div className={styles.modal} onMouseDown={(event) => event.stopPropagation()}><div className={styles.modalHeader}><h2>{t("detailTitle")}</h2><button onClick={closeDetail} aria-label={common("cancel")}>×</button></div><div style={{ padding: "0 24px 24px" }}>{detailLoading ? <p>{t("loading")}</p> : detailError ? <div className={styles.formError}>{detailError}</div> : detail && <WithdrawalDetailGrid withdrawal={detail} owner={false} />}</div></div></div>}
  </section>;
}
