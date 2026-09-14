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

export default function TeamLeadTeamPage() {
  const t = useTranslations("teamLead");
  const common = useTranslations("common");
  const format = useAppFormat();
  const [offset, setOffset] = useState(0);
  const query = useApiQuery(() => teamLeadApi.team(undefined, undefined, PAGE_SIZE, offset), `team-lead-team:${offset}`);

  return <section>
    <div className={styles.contentHeader} style={{ padding: 0, border: 0, marginBottom: 27 }}>
      <PageHeading eyebrow={t("eyebrow")} title={t("teamTitle")} text={t("teamSubtitle")} />
    </div>
    <div className={styles.contentCard}>
      {query.loading ? <div className={styles.state}>{t("loading")}</div>
        : query.error ? <div className={`${styles.state} ${styles.errorText}`}>{query.error}</div>
        : !query.data?.items.length ? <div className={styles.state}>{t("teamEmpty")}</div>
        : <div className={styles.tableScroll}><table><thead><tr><th>{t("username")}</th><th>{t("fullName")}</th><th>{common("status")}</th><th>{t("joined")}</th></tr></thead><tbody>
            {query.data.items.map((member) => <tr key={member.id}>
              <td>{member.username}</td>
              <td>{member.full_name}</td>
              <td>{member.is_active ? t("memberActive") : t("memberInactive")}</td>
              <td>{format.date(member.created_at)}</td>
            </tr>)}
          </tbody></table></div>}
      {query.data && <Pager offset={offset} limit={PAGE_SIZE} itemCount={query.data.items.length} total={query.data.total} onPage={setOffset} />}
    </div>
  </section>;
}
