"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { useAppFormat } from "@/features/i18n/use-app-format";
import { analyticsApi } from "@/lib/api/analytics";
import { useApiQuery } from "@/lib/hooks/use-api-query";

import { Heading } from "./owner-components";
import styles from "./owner.module.css";

export default function OwnerDashboard() {
  const t = useTranslations("dashboard");
  const nav = useTranslations("navigation");
  const common = useTranslations("common");
  const format = useAppFormat();
  const summary = useApiQuery(analyticsApi.summary, "owner-summary");
  const activity = useApiQuery(analyticsApi.activity, "owner-activity");
  const data = summary.data;
  return <section><Heading title={t("ownerTitle")} text={t("ownerSubtitle")} />
    {summary.error && <div className={styles.error}>{summary.error}</div>}
    <div className={styles.kpiGrid}>
      <Kpi label={t("users")} value={data?.accounts.users_total} detail={t("activeCount", { count: data?.accounts.users_active ?? 0 })} loading={summary.loading} />
      <Kpi label={t("merchants")} value={data?.accounts.merchants_total} detail={t("activeCount", { count: data?.accounts.merchants_active ?? 0 })} loading={summary.loading} />
      <Kpi label={t("deals")} value={data?.deals.total} detail={t("completedCount", { count: data?.deals.completed ?? 0 })} loading={summary.loading} accent />
      <Kpi label={t("openAppeals")} value={data?.appeals.open} detail={t("reviewCount", { count: data?.appeals.under_review ?? 0 })} loading={summary.loading} />
    </div>
    <div className={styles.financeGrid}><Finance label={t("userBalance")} value={data?.financials.total_user_available_usdt} /><Finance label={t("frozen")} value={data?.financials.total_user_frozen_usdt} /><Finance label={t("merchantBalance")} value={data?.financials.total_merchant_available_usdt} /><Finance label={t("dealVolume")} value={data?.financials.total_completed_deal_volume_usdt} /></div>
    <div className={styles.dashboardGrid}><article className={styles.activity}><header><div><span>{t("liveActivityEyebrow")}</span><h2>{t("lastEvents")}</h2></div><button onClick={activity.refetch}>{common("refresh")}</button></header>{activity.loading ? <div className={styles.state}>{common("loading")}</div> : activity.error ? <div className={`${styles.state} ${styles.errorText}`}>{activity.error}</div> : !activity.data?.length ? <div className={styles.state}>{t("noEvents")}</div> : activity.data.map((item) => <div className={styles.activityRow} key={`${item.type}-${item.entity_id}`}><i /><div><strong>{item.description}</strong><span>{item.public_id || item.type}</span></div><time>{format.dateTime(item.created_at)}</time></div>)}</article>
      <aside className={styles.quick}><span>{t("quickAccessEyebrow")}</span><h2>{t("quickAccess")}</h2><Link href="/owner/accounts">{nav("accounts")} <b>→</b></Link><Link href="/owner/deals">{nav("deals")} <b>→</b></Link><Link href="/owner/appeals">{nav("appeals")} <b>→</b></Link><Link href="/owner/analytics">{t("fullAnalytics")} <b>→</b></Link></aside></div>
  </section>;

  function Finance({ label, value }: { label: string; value?: string }) { return <article><span>{label}</span><strong>{format.number(value || 0)}</strong><small>USDT</small></article>; }
}

function Kpi({ label, value, detail, loading, accent = false }: { label: string; value?: number; detail: string; loading: boolean; accent?: boolean }) { return <article className={styles.kpi}><span>{label}</span><strong className={accent ? styles.accent : ""}>{loading ? "—" : value ?? 0}</strong><small>{detail}</small></article>; }
