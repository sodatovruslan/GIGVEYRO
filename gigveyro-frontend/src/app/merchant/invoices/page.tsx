"use client";

import { type FormEvent, useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { PageHeading } from "@/app/user/user-components";
import { useAppFormat } from "@/features/i18n/use-app-format";
import { useEnumLabels } from "@/features/i18n/use-enum-labels";
import { useLocalizedError } from "@/features/i18n/use-localized-error";
import { isInvoiceNotCancellable, mapInvoiceFieldErrors, type InvoiceFieldErrors } from "@/features/invoices/validation";
import { invoicesApi } from "@/lib/api/invoices";
import type { Invoice, InvoiceTimeline } from "@/lib/api/types";
import { useApiQuery } from "@/lib/hooks/use-api-query";
import { Pager } from "@/components/ui/pager";
import { InvoiceDetailGrid } from "@/components/invoices/invoice-detail";
import { InvoiceTimelineSection } from "@/components/invoices/invoice-timeline";
import { queryInvalidation } from "@/lib/query/invalidation";

import styles from "../../user/user.module.css";

const PAGE_SIZE = 20;

function paymentLink(publicId: string) {
  if (typeof window === "undefined") return "";
  return `${window.location.origin}/pay/${publicId}`;
}

export default function MerchantInvoicesPage() {
  const t = useTranslations("invoices");
  const common = useTranslations("common");
  const labels = useEnumLabels();
  const format = useAppFormat();
  const localizeError = useLocalizedError();
  const [offset, setOffset] = useState(0);
  const query = useApiQuery(() => invoicesApi.list(undefined, PAGE_SIZE, offset), `merchant-invoices:${offset}`);
  const [modal, setModal] = useState(false);
  const [amount, setAmount] = useState("");
  const [description, setDescription] = useState("");
  const [externalReference, setExternalReference] = useState("");
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<InvoiceFieldErrors>({});
  const [saving, setSaving] = useState(false);
  const [detail, setDetail] = useState<Invoice | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [linkCopied, setLinkCopied] = useState(false);
  const [timeline, setTimeline] = useState<InvoiceTimeline | null>(null);

  useEffect(() => {
    const id = detail?.id;
    if (!id) return;
    return queryInvalidation.subscribe(`merchant-invoice:${id}`, () => {
      void invoicesApi.get(id).then(setDetail).catch((reason) => setDetailError(localizeError(reason)));
      void invoicesApi.timeline(id).then(setTimeline).catch(() => undefined);
    });
  }, [detail?.id, localizeError]);

  async function openDetail(id: string) {
    setDetail(null); setDetailError(""); setDetailLoading(true); setLinkCopied(false); setTimeline(null);
    try { setDetail(await invoicesApi.get(id)); }
    catch (reason) { setDetailError(localizeError(reason)); }
    finally { setDetailLoading(false); }
    // Best-effort: the timeline is a read-only supplement to the invoice
    // detail above, never a hard requirement for the detail view to work.
    void invoicesApi.timeline(id).then(setTimeline).catch(() => undefined);
  }
  function closeDetail() { setDetail(null); setDetailError(""); setTimeline(null); }

  async function create(event: FormEvent) {
    event.preventDefault(); setSaving(true); setError(""); setFieldErrors({});
    try {
      await invoicesApi.create({ amount, description: description || null, external_reference: externalReference || null });
      setModal(false); setAmount(""); setDescription(""); setExternalReference(""); await query.refetch();
    } catch (reason) {
      const mapped = mapInvoiceFieldErrors(reason, { invalidAmount: t("validation.amount") });
      setFieldErrors(mapped);
      if (!Object.keys(mapped).length) setError(localizeError(reason));
    } finally { setSaving(false); }
  }

  async function cancel(id: string) {
    setError("");
    try { await invoicesApi.cancel(id); await query.refetch(); }
    catch (reason) {
      setError(isInvoiceNotCancellable(reason) ? t("notCancellable") : localizeError(reason));
      await query.refetch();
    }
  }

  async function copyLink(publicId: string) {
    try { await navigator.clipboard.writeText(paymentLink(publicId)); setLinkCopied(true); }
    catch { /* clipboard access can be denied - the link remains visible for manual copy */ }
  }

  return <section>
    <div className={styles.contentHeader} style={{ padding: 0, border: 0, marginBottom: 27 }}>
      <PageHeading eyebrow={t("eyebrow")} title={t("merchantTitle")} text={t("merchantSubtitle")} />
      <button onClick={() => setModal(true)}>＋ {t("create")}</button>
    </div>
    {error && <div className={styles.inlineError}>{error}</div>}
    <div className={styles.contentCard}>
      {query.loading ? <div className={styles.state}>{t("loading")}</div>
        : query.error ? <div className={`${styles.state} ${styles.errorText}`}>{query.error}</div>
        : !query.data?.items.length ? <div className={styles.state}>{t("empty")}</div>
        : <div className={styles.tableScroll}><table><thead><tr><th>ID</th><th>{common("date")}</th><th>{t("description")}</th><th>{common("amount")}</th><th>{common("status")}</th><th /></tr></thead><tbody>
            {query.data.items.map((item) => <tr key={item.id} className={styles.row} onClick={() => void openDetail(item.id)}>
              <td>{item.public_id}</td>
              <td>{format.dateTime(item.created_at)}</td>
              <td>{item.description || "—"}</td>
              <td>{item.amount} USDT</td>
              <td>{labels.invoice(item.status)}</td>
              <td onClick={(event) => event.stopPropagation()}>{item.status === "pending_payment" && <button className={styles.negative} onClick={() => void cancel(item.id)}>{t("cancelAction")}</button>}</td>
            </tr>)}
          </tbody></table></div>}
      {query.data && <Pager offset={offset} limit={PAGE_SIZE} itemCount={query.data.items.length} total={query.data.total} onPage={setOffset} />}
    </div>
    {modal && <div className={styles.modalBackdrop} onMouseDown={() => setModal(false)}><div className={styles.modal} onMouseDown={(event) => event.stopPropagation()}>
      <div className={styles.modalHeader}><h2>{t("newTitle")}</h2><button onClick={() => setModal(false)} aria-label={common("cancel")}>×</button></div>
      <form className={styles.form} onSubmit={create}>
        <label>{common("amount")} USDT<input aria-invalid={Boolean(fieldErrors.amount)} required type="number" min="0.00000001" step="0.00000001" value={amount} onChange={(event) => { setAmount(event.target.value); setFieldErrors((value) => ({ ...value, amount: undefined })); }} />{fieldErrors.amount && <span className={styles.formError}>{fieldErrors.amount}</span>}</label>
        <label>{t("description")}<input maxLength={500} value={description} onChange={(event) => setDescription(event.target.value)} /></label>
        <label>{t("externalReference")}<input maxLength={255} value={externalReference} onChange={(event) => setExternalReference(event.target.value)} /></label>
        {error && <div className={styles.formError}>{error}</div>}
        <div className={styles.formActions}><button type="button" onClick={() => setModal(false)}>{common("cancel")}</button><button disabled={saving}>{saving ? common("creating") : common("create")}</button></div>
      </form>
    </div></div>}
    {(detailLoading || detail || detailError) && <div className={styles.modalBackdrop} onMouseDown={closeDetail}><div className={styles.modal} onMouseDown={(event) => event.stopPropagation()}>
      <div className={styles.modalHeader}><h2>{t("detailTitle")}</h2><button onClick={closeDetail} aria-label={common("cancel")}>×</button></div>
      <div style={{ padding: "0 24px 24px" }}>
        {detailLoading ? <p>{t("loading")}</p>
          : detailError ? <div className={styles.formError}>{detailError}</div>
          : detail && <>
            <InvoiceDetailGrid invoice={detail} paymentLink={paymentLink(detail.public_id)} onCopyLink={() => void copyLink(detail.public_id)} linkCopied={linkCopied} />
            {timeline && <InvoiceTimelineSection timeline={timeline} />}
          </>}
      </div>
    </div></div>}
  </section>;
}
