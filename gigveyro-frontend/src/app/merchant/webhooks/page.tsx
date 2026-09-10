"use client";

import { type FormEvent, useState } from "react";
import { useTranslations } from "next-intl";

import { PageHeading } from "@/app/user/user-components";
import { useAppFormat } from "@/features/i18n/use-app-format";
import { useLocalizedError } from "@/features/i18n/use-localized-error";
import { webhooksApi } from "@/lib/api/webhooks";
import type { Webhook, WebhookCreated, WebhookDelivery } from "@/lib/api/types";
import { useApiQuery } from "@/lib/hooks/use-api-query";
import { Pager } from "@/components/ui/pager";

import styles from "../../user/user.module.css";

const PAGE_SIZE = 20;

export default function MerchantWebhooksPage() {
  const t = useTranslations("webhooks");
  const common = useTranslations("common");
  const format = useAppFormat();
  const localizeError = useLocalizedError();
  const [offset, setOffset] = useState(0);
  const query = useApiQuery(() => webhooksApi.list(PAGE_SIZE, offset), `merchant-webhooks:${offset}`);

  const [modal, setModal] = useState(false);
  const [url, setUrl] = useState("");
  const [invoicePaid, setInvoicePaid] = useState(true);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [created, setCreated] = useState<WebhookCreated | null>(null);
  const [copied, setCopied] = useState(false);

  const [deliveriesFor, setDeliveriesFor] = useState<Webhook | null>(null);
  const [deliveries, setDeliveries] = useState<WebhookDelivery[] | null>(null);
  const [deliveriesError, setDeliveriesError] = useState("");

  async function create(event: FormEvent) {
    event.preventDefault(); setSaving(true); setError("");
    const eventTypes = invoicePaid ? ["invoice.paid"] : [];
    if (!eventTypes.length) { setError(t("validation.events")); setSaving(false); return; }
    try {
      const result = await webhooksApi.create(url, eventTypes);
      setModal(false); setUrl(""); setCreated(result); setCopied(false); await query.refetch();
    } catch (reason) { setError(localizeError(reason)); }
    finally { setSaving(false); }
  }

  async function toggleStatus(webhook: Webhook) {
    setError("");
    try { await webhooksApi.update(webhook.id, { status: webhook.status === "active" ? "disabled" : "active" }); await query.refetch(); }
    catch (reason) { setError(localizeError(reason)); }
  }

  async function openDeliveries(webhook: Webhook) {
    setDeliveriesFor(webhook); setDeliveries(null); setDeliveriesError("");
    try { setDeliveries((await webhooksApi.deliveries(webhook.id)).items); }
    catch (reason) { setDeliveriesError(localizeError(reason)); }
  }

  async function copySecret() {
    if (!created) return;
    try { await navigator.clipboard.writeText(created.secret); setCopied(true); }
    catch { /* clipboard access can be denied - the secret remains visible for manual copy */ }
  }

  return <section>
    <div className={styles.contentHeader} style={{ padding: 0, border: 0, marginBottom: 27 }}>
      <PageHeading eyebrow={t("eyebrow")} title={t("title")} text={t("subtitle")} />
      <button onClick={() => setModal(true)}>＋ {t("create")}</button>
    </div>
    {error && <div className={styles.inlineError}>{error}</div>}
    <div className={styles.contentCard}>
      {query.loading ? <div className={styles.state}>{t("loading")}</div>
        : query.error ? <div className={`${styles.state} ${styles.errorText}`}>{query.error}</div>
        : !query.data?.items.length ? <div className={styles.state}>{t("empty")}</div>
        : <div className={styles.tableScroll}><table><thead><tr><th>{t("url")}</th><th>{t("events")}</th><th>{common("status")}</th><th>{common("date")}</th><th /></tr></thead><tbody>
            {query.data.items.map((item) => <tr key={item.id}>
              <td style={{ overflowWrap: "anywhere" }}>{item.url}</td>
              <td>{item.event_types.map((event) => event === "invoice.paid" ? t("eventInvoicePaid") : event).join(", ")}</td>
              <td>{item.status === "active" ? t("statusActive") : t("statusDisabled")}</td>
              <td>{format.dateTime(item.created_at)}</td>
              <td>
                <button onClick={() => void openDeliveries(item)}>{t("viewDeliveries")}</button>{" "}
                <button className={item.status === "active" ? styles.negative : undefined} onClick={() => void toggleStatus(item)}>{item.status === "active" ? t("disable") : t("enable")}</button>
              </td>
            </tr>)}
          </tbody></table></div>}
      {query.data && <Pager offset={offset} limit={PAGE_SIZE} itemCount={query.data.items.length} total={query.data.total} onPage={setOffset} />}
    </div>

    {modal && <div className={styles.modalBackdrop} onMouseDown={() => setModal(false)}><div className={styles.modal} onMouseDown={(event) => event.stopPropagation()}>
      <div className={styles.modalHeader}><h2>{t("newTitle")}</h2><button onClick={() => setModal(false)} aria-label={common("cancel")}>×</button></div>
      <form className={styles.form} onSubmit={create}>
        <label>{t("url")}<input required type="url" placeholder="https://example.com/webhooks/gigapay" value={url} onChange={(event) => setUrl(event.target.value)} /></label>
        <label style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
          <input type="checkbox" checked={invoicePaid} onChange={(event) => setInvoicePaid(event.target.checked)} />
          {t("eventInvoicePaid")}
        </label>
        {error && <div className={styles.formError}>{error}</div>}
        <div className={styles.formActions}><button type="button" onClick={() => setModal(false)}>{common("cancel")}</button><button disabled={saving}>{saving ? common("creating") : common("create")}</button></div>
      </form>
    </div></div>}

    {created && <div className={styles.modalBackdrop} onMouseDown={() => setCreated(null)}><div className={styles.modal} onMouseDown={(event) => event.stopPropagation()}>
      <div className={styles.modalHeader}><h2>{t("createdTitle")}</h2><button onClick={() => setCreated(null)} aria-label={common("cancel")}>×</button></div>
      <div style={{ padding: "0 24px 24px" }}>
        <p className={styles.formError}>{t("createdWarning")}</p>
        <p><code style={{ overflowWrap: "anywhere" }}>{created.secret}</code></p>
        <div className={styles.formActions}>
          <button type="button" onClick={() => void copySecret()}>{copied ? t("copied") : t("copySecret")}</button>
          <button type="button" onClick={() => setCreated(null)}>{t("done")}</button>
        </div>
      </div>
    </div></div>}

    {deliveriesFor && <div className={styles.modalBackdrop} onMouseDown={() => setDeliveriesFor(null)}><div className={styles.modal} onMouseDown={(event) => event.stopPropagation()}>
      <div className={styles.modalHeader}><h2>{t("deliveriesTitle")}</h2><button onClick={() => setDeliveriesFor(null)} aria-label={common("cancel")}>×</button></div>
      <div style={{ padding: "0 24px 24px" }}>
        {deliveriesError ? <div className={styles.formError}>{deliveriesError}</div>
          : deliveries === null ? <p>{common("loading")}</p>
          : !deliveries.length ? <p>{t("deliveriesEmpty")}</p>
          : <div className={styles.tableScroll}><table><thead><tr><th>{t("deliveryEvent")}</th><th>{t("deliveryStatus")}</th><th>{t("deliveryAttempts")}</th><th>{t("deliveryResponse")}</th><th>{t("deliveryCreated")}</th></tr></thead><tbody>
              {deliveries.map((delivery) => <tr key={delivery.id}>
                <td>{delivery.event_type}</td>
                <td>{delivery.status}</td>
                <td>{delivery.attempts}/{delivery.max_attempts}</td>
                <td>{delivery.last_response_status ?? "—"}</td>
                <td>{format.dateTime(delivery.created_at)}</td>
              </tr>)}
            </tbody></table></div>}
      </div>
    </div></div>}
  </section>;
}
