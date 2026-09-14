"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { PageHeading } from "@/app/user/user-components";
import { useAppFormat } from "@/features/i18n/use-app-format";
import { teamLeadApi } from "@/lib/api/team-lead";
import { useApiQuery } from "@/lib/hooks/use-api-query";

import styles from "../user/user.module.css";

export default function TeamLeadDashboard() {
  const t = useTranslations("dashboard");
  const format = useAppFormat();
  const dashboard = useApiQuery(teamLeadApi.dashboard, "team-lead-dashboard");
  const data = dashboard.data;

  return <section>
    <PageHeading eyebrow={t("teamLeadEyebrow")} title={t("teamLeadTitle")} text={t("teamLeadSubtitle")} />
    <div className={styles.balanceGrid}>
      <article className={styles.balanceCard}><span>{t("availableBalance")}</span><div><strong className={styles.accent}>{dashboard.loading ? "—" : format.number(data?.profit_available || 0)}</strong><small>USDT</small></div></article>
      <article className={styles.balanceCard}><span>{t("withdrawalRequests")}</span><div><strong>{dashboard.loading ? "—" : format.number(data?.profit_pending_withdrawal || 0)}</strong><small>USDT</small></div></article>
      <article className={styles.balanceCard}><span>{t("teamSize")}</span><div><strong>{dashboard.loading ? "—" : data?.team_size ?? 0}</strong></div></article>
    </div>
    {dashboard.error && <div className={styles.inlineError}>{dashboard.error}</div>}
    <div className={styles.dashboardGrid}>
      <article className={styles.trafficCard}>
        <div className={styles.cardHeading}><div><span>{t("dealsEyebrow")}</span><h2>{t("teamDeals")}</h2></div><Link href="/team_lead/team">{t("open")}</Link></div>
        <p>{t("teamLeadDealsText")}</p>
      </article>
      <article className={styles.requisiteSummary}>
        <div className={styles.cardHeading}><div><span>{t("payoutsEyebrow")}</span><h2>{t("dealVolume")}</h2></div><Link href="/team_lead/profit">{t("manage")}</Link></div>
        <div className={styles.bigNumber}>{dashboard.loading ? "—" : format.number(data?.deal_volume || 0)}<small>{t("dealCount", { count: data?.deal_count ?? 0 })}</small></div>
      </article>
    </div>
  </section>;
}
