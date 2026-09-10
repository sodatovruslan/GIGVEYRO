"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { PageHeading } from "@/app/user/user-components";
import { useAppFormat } from "@/features/i18n/use-app-format";
import { useLocalizedError } from "@/features/i18n/use-localized-error";
import { ownerApiKeysApi } from "@/lib/api/owner-api-keys";
import { useApiQuery } from "@/lib/hooks/use-api-query";
import { Pager } from "@/components/ui/pager";

import styles from "../../user/user.module.css";

const PAGE_SIZE = 20;

export default function OwnerApiKeysPage() {
  const t = useTranslations("apiKeys");
  const common = useTranslations("common");
  const format = useAppFormat();
  const localizeError = useLocalizedError();
  const [offset, setOffset] = useState(0);
  const query = useApiQuery(() => ownerApiKeysApi.list(PAGE_SIZE, offset), `owner-api-keys:${offset}`);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);

  async function revoke(id: string) {
    if (!window.confirm(t("revokeConfirm"))) return;
    setError(""); setBusyId(id);
    try { await ownerApiKeysApi.revoke(id); await query.refetch(); }
    catch (reason) { setError(localizeError(reason)); }
    finally { setBusyId(null); }
  }

  return <section>
    <PageHeading eyebrow={t("eyebrow")} title={t("ownerTitle")} text={t("ownerSubtitle")} />
    {error && <div className={styles.inlineError}>{error}</div>}
    <div className={styles.contentCard}>
      {query.loading ? <div className={styles.state}>{t("loading")}</div>
        : query.error ? <div className={`${styles.state} ${styles.errorText}`}>{query.error}</div>
        : !query.data?.items.length ? <div className={styles.state}>{t("empty")}</div>
        : <div className={styles.tableScroll}><table><thead><tr><th>{t("merchant")}</th><th>{t("label")}</th><th>{t("prefix")}</th><th>{common("status")}</th><th>{t("lastUsed")}</th><th>{common("date")}</th><th /></tr></thead><tbody>
            {query.data.items.map((item) => <tr key={item.id}>
              <td><code>{item.merchant_id}</code></td>
              <td>{item.label}</td>
              <td><code>{item.key_prefix}…</code></td>
              <td>{item.status === "active" ? common("active") : t("statusRevoked")}</td>
              <td>{item.last_used_at ? format.dateTime(item.last_used_at) : t("never")}</td>
              <td>{format.dateTime(item.created_at)}</td>
              <td>{item.status === "active" && <button className={styles.negative} disabled={busyId === item.id} onClick={() => void revoke(item.id)}>{t("revokeAction")}</button>}</td>
            </tr>)}
          </tbody></table></div>}
      {query.data && <Pager offset={offset} limit={PAGE_SIZE} itemCount={query.data.items.length} total={query.data.total} onPage={setOffset} />}
    </div>
  </section>;
}
