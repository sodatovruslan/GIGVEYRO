"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { PageHeading } from "@/app/user/user-components";
import { useAppFormat } from "@/features/i18n/use-app-format";
import { useEnumLabels } from "@/features/i18n/use-enum-labels";
import { useLocalizedError } from "@/features/i18n/use-localized-error";
import { ownerTeamLeadsApi } from "@/lib/api/owner-team-leads";
import { useApiQuery } from "@/lib/hooks/use-api-query";
import { Pager } from "@/components/ui/pager";

import styles from "../../user/user.module.css";

const PAGE_SIZE = 20;

export default function OwnerTeamLeadWithdrawalsPage() {
  const t = useTranslations("withdrawals");
  const tl = useTranslations("teamLead");
  const common = useTranslations("common");
  const labels = useEnumLabels();
  const format = useAppFormat();
  const localizeError = useLocalizedError();
  const [offset, setOffset] = useState(0);
  const query = useApiQuery(() => ownerTeamLeadsApi.withdrawals.list(undefined, PAGE_SIZE, offset), `owner-team-lead-withdrawals:${offset}`);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);

  async function approve(id: string) {
    setError(""); setBusyId(id);
    try { await ownerTeamLeadsApi.withdrawals.approve(id, null); await query.refetch(); }
    catch (reason) { setError(localizeError(reason)); }
    finally { setBusyId(null); }
  }

  async function reject(id: string) {
    setError(""); setBusyId(id);
    try { await ownerTeamLeadsApi.withdrawals.reject(id, null); await query.refetch(); }
    catch (reason) { setError(localizeError(reason)); }
    finally { setBusyId(null); }
  }

  async function markPaid(id: string) {
    setError(""); setBusyId(id);
    try { await ownerTeamLeadsApi.withdrawals.markPaid(id, null); await query.refetch(); }
    catch (reason) { setError(localizeError(reason)); }
    finally { setBusyId(null); }
  }

  return <section>
    <div className={styles.contentHeader} style={{ padding: 0, border: 0, marginBottom: 27 }}>
      <PageHeading eyebrow={tl("eyebrow")} title={tl("ownerWithdrawalsTitle")} text={tl("ownerWithdrawalsSubtitle")} />
    </div>
    {error && <div className={styles.inlineError}>{error}</div>}
    <div className={styles.contentCard}>
      {query.loading ? <div className={styles.state}>{t("loading")}</div>
        : query.error ? <div className={`${styles.state} ${styles.errorText}`}>{query.error}</div>
        : !query.data?.items.length ? <div className={styles.state}>{t("empty")}</div>
        : <div className={styles.tableScroll}><table><thead><tr><th>ID</th><th>{common("date")}</th><th>{t("destination")}</th><th>{common("amount")}</th><th>{common("status")}</th><th /></tr></thead><tbody>
            {query.data.items.map((item) => <tr key={item.id}>
              <td>{item.public_id}</td>
              <td>{format.dateTime(item.created_at)}</td>
              <td>{labels.destination(item.destination_type)}<br />{item.destination}</td>
              <td>{item.amount} {item.currency.toUpperCase()}</td>
              <td>{labels.withdrawal(item.status)}</td>
              <td>
                {item.status === "pending" && <>
                  <button disabled={busyId === item.id} onClick={() => void approve(item.id)}>{t("approve")}</button>{" "}
                  <button className={styles.negative} disabled={busyId === item.id} onClick={() => void reject(item.id)}>{t("reject")}</button>
                </>}
                {item.status === "approved" && <button disabled={busyId === item.id} onClick={() => void markPaid(item.id)}>{t("markPaid")}</button>}
              </td>
            </tr>)}
          </tbody></table></div>}
      {query.data && <Pager offset={offset} limit={PAGE_SIZE} itemCount={query.data.items.length} total={query.data.total} onPage={setOffset} />}
    </div>
  </section>;
}
