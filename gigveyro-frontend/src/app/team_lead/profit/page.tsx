"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { PageHeading } from "@/app/user/user-components";
import { useAppFormat } from "@/features/i18n/use-app-format";
import { teamLeadApi } from "@/lib/api/team-lead";
import { useApiQuery } from "@/lib/hooks/use-api-query";
import { Pager } from "@/components/ui/pager";

import styles from "../../user/user.module.css";

const PAGE_SIZE = 20;

export default function TeamLeadProfitPage() {
  const t = useTranslations("teamLead");
  const common = useTranslations("common");
  const format = useAppFormat();
  const [offset, setOffset] = useState(0);
  const dashboard = useApiQuery(teamLeadApi.dashboard, "team-lead-dashboard-profit");
  const ledger = useApiQuery(() => teamLeadApi.profitLedger(PAGE_SIZE, offset), `team-lead-profit-ledger:${offset}`);

  return <section>
    <div className={styles.contentHeader} style={{ padding: 0, border: 0, marginBottom: 27 }}>
      <PageHeading eyebrow={t("eyebrow")} title={t("profitTitle")} text={t("profitSubtitle")} />
    </div>
    <div className={styles.balanceGrid}>
      <article className={styles.balanceCard}><span>{t("profitAvailable")}</span><div><strong className={styles.accent}>{dashboard.loading ? "—" : format.number(dashboard.data?.profit_available || 0)}</strong><small>USDT</small></div></article>
      <article className={styles.balanceCard}><span>{t("profitPending")}</span><div><strong>{dashboard.loading ? "—" : format.number(dashboard.data?.profit_pending_withdrawal || 0)}</strong><small>USDT</small></div></article>
    </div>
    <div className={styles.contentCard} style={{ marginTop: 20 }}>
      {ledger.loading ? <div className={styles.state}>{t("loading")}</div>
        : ledger.error ? <div className={`${styles.state} ${styles.errorText}`}>{ledger.error}</div>
        : !ledger.data?.items.length ? <div className={styles.state}>{t("profitEmpty")}</div>
        : <div className={styles.tableScroll}><table><thead><tr><th>{common("date")}</th><th>{common("amount")}</th></tr></thead><tbody>
            {ledger.data.items.map((entry) => <tr key={entry.id}>
              <td>{format.dateTime(entry.created_at)}</td>
              <td>+{format.number(entry.amount)} USDT</td>
            </tr>)}
          </tbody></table></div>}
      {ledger.data && <Pager offset={offset} limit={PAGE_SIZE} itemCount={ledger.data.items.length} total={ledger.data.total} onPage={setOffset} />}
    </div>
  </section>;
}
