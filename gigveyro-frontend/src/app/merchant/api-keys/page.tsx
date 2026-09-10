"use client";

import { type FormEvent, useState } from "react";
import { useTranslations } from "next-intl";

import { PageHeading } from "@/app/user/user-components";
import { useAppFormat } from "@/features/i18n/use-app-format";
import { useLocalizedError } from "@/features/i18n/use-localized-error";
import { apiKeysApi } from "@/lib/api/api-keys";
import type { ApiKeyCreated } from "@/lib/api/types";
import { useApiQuery } from "@/lib/hooks/use-api-query";
import { Pager } from "@/components/ui/pager";

import styles from "../../user/user.module.css";

const PAGE_SIZE = 20;

export default function MerchantApiKeysPage() {
  const t = useTranslations("apiKeys");
  const common = useTranslations("common");
  const format = useAppFormat();
  const localizeError = useLocalizedError();
  const [offset, setOffset] = useState(0);
  const query = useApiQuery(() => apiKeysApi.list(PAGE_SIZE, offset), `merchant-api-keys:${offset}`);
  const [modal, setModal] = useState(false);
  const [label, setLabel] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);
  const [copied, setCopied] = useState(false);

  async function create(event: FormEvent) {
    event.preventDefault(); setSaving(true); setError("");
    try { const result = await apiKeysApi.create(label); setModal(false); setLabel(""); setCreated(result); setCopied(false); await query.refetch(); }
    catch (reason) { setError(localizeError(reason)); }
    finally { setSaving(false); }
  }

  async function revoke(id: string) {
    if (!window.confirm(t("revokeConfirm"))) return;
    setError("");
    try { await apiKeysApi.revoke(id); await query.refetch(); }
    catch (reason) { setError(localizeError(reason)); }
  }

  async function copyKey() {
    if (!created) return;
    try { await navigator.clipboard.writeText(created.raw_key); setCopied(true); }
    catch { /* clipboard access can be denied - the key remains visible for manual copy */ }
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
        : <div className={styles.tableScroll}><table><thead><tr><th>{t("label")}</th><th>{t("prefix")}</th><th>{common("status")}</th><th>{t("lastUsed")}</th><th>{common("date")}</th><th /></tr></thead><tbody>
            {query.data.items.map((item) => <tr key={item.id}>
              <td>{item.label}</td>
              <td><code>{item.key_prefix}…</code></td>
              <td>{item.status === "active" ? common("active") : t("statusRevoked")}</td>
              <td>{item.last_used_at ? format.dateTime(item.last_used_at) : t("never")}</td>
              <td>{format.dateTime(item.created_at)}</td>
              <td>{item.status === "active" && <button className={styles.negative} onClick={() => void revoke(item.id)}>{t("revokeAction")}</button>}</td>
            </tr>)}
          </tbody></table></div>}
      {query.data && <Pager offset={offset} limit={PAGE_SIZE} itemCount={query.data.items.length} total={query.data.total} onPage={setOffset} />}
    </div>
    {modal && <div className={styles.modalBackdrop} onMouseDown={() => setModal(false)}><div className={styles.modal} onMouseDown={(event) => event.stopPropagation()}>
      <div className={styles.modalHeader}><h2>{t("newTitle")}</h2><button onClick={() => setModal(false)} aria-label={common("cancel")}>×</button></div>
      <form className={styles.form} onSubmit={create}>
        <label>{t("label")}<input required minLength={1} maxLength={100} value={label} onChange={(event) => setLabel(event.target.value)} /></label>
        {error && <div className={styles.formError}>{error}</div>}
        <div className={styles.formActions}><button type="button" onClick={() => setModal(false)}>{common("cancel")}</button><button disabled={saving}>{saving ? common("creating") : common("create")}</button></div>
      </form>
    </div></div>}
    {created && <div className={styles.modalBackdrop} onMouseDown={() => setCreated(null)}><div className={styles.modal} onMouseDown={(event) => event.stopPropagation()}>
      <div className={styles.modalHeader}><h2>{t("createdTitle")}</h2><button onClick={() => setCreated(null)} aria-label={common("cancel")}>×</button></div>
      <div style={{ padding: "0 24px 24px" }}>
        <p className={styles.formError}>{t("createdWarning")}</p>
        <p><code style={{ overflowWrap: "anywhere" }}>{created.raw_key}</code></p>
        <div className={styles.formActions}>
          <button type="button" onClick={() => void copyKey()}>{copied ? t("copied") : t("copyKey")}</button>
          <button type="button" onClick={() => setCreated(null)}>{t("done")}</button>
        </div>
      </div>
    </div></div>}
  </section>;
}
