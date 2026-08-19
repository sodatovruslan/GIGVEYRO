"use client";

import Link from "next/link";

import { analyticsApi } from "@/lib/api/analytics";
import { useApiQuery } from "@/lib/hooks/use-api-query";

import styles from "./owner.module.css";
import { Heading } from "./owner-components";

export default function OwnerDashboard() {
  const summary = useApiQuery(analyticsApi.summary, "owner-summary");
  const activity = useApiQuery(analyticsApi.activity, "owner-activity");
  const data = summary.data;
  return <section><Heading title="Панель управления" text="Операционное состояние платформы" />
    {summary.error && <div className={styles.error}>{summary.error}</div>}
    <div className={styles.kpiGrid}>
      <Kpi label="Пользователи" value={data?.accounts.users_total} detail={`${data?.accounts.users_active ?? 0} активных`} loading={summary.loading}/>
      <Kpi label="Мерчанты" value={data?.accounts.merchants_total} detail={`${data?.accounts.merchants_active ?? 0} активных`} loading={summary.loading}/>
      <Kpi label="Сделки" value={data?.deals.total} detail={`${data?.deals.completed ?? 0} завершено`} loading={summary.loading} accent/>
      <Kpi label="Открытые споры" value={data?.appeals.open} detail={`${data?.appeals.under_review ?? 0} на рассмотрении`} loading={summary.loading}/>
    </div>
    <div className={styles.financeGrid}><Finance label="Баланс пользователей" value={data?.financials.total_user_available_usdt}/><Finance label="Заморожено" value={data?.financials.total_user_frozen_usdt}/><Finance label="Баланс мерчантов" value={data?.financials.total_merchant_available_usdt}/><Finance label="Объём сделок" value={data?.financials.total_completed_deal_volume_usdt}/></div>
    <div className={styles.dashboardGrid}><article className={styles.activity}><header><div><span>LIVE ACTIVITY</span><h2>Последние события</h2></div><button onClick={activity.refetch}>Обновить</button></header>{activity.loading?<div className={styles.state}>Загрузка…</div>:activity.error?<div className={`${styles.state} ${styles.errorText}`}>{activity.error}</div>:!activity.data?.length?<div className={styles.state}>Событий пока нет</div>:activity.data.map((item)=><div className={styles.activityRow} key={`${item.type}-${item.entity_id}`}><i/><div><strong>{item.description}</strong><span>{item.public_id||item.type}</span></div><time>{new Intl.DateTimeFormat("ru-RU",{dateStyle:"short",timeStyle:"short"}).format(new Date(item.created_at))}</time></div>)}</article>
      <aside className={styles.quick}><span>QUICK ACCESS</span><h2>Управление</h2><Link href="/owner/accounts">Аккаунты <b>→</b></Link><Link href="/owner/deals">Сделки <b>→</b></Link><Link href="/owner/appeals">Апелляции <b>→</b></Link><Link href="/owner/analytics">Полная аналитика <b>→</b></Link></aside></div>
  </section>;
}

function Kpi({label,value,detail,loading,accent=false}:{label:string;value?:number;detail:string;loading:boolean;accent?:boolean}){return <article className={styles.kpi}><span>{label}</span><strong className={accent?styles.accent:""}>{loading?"—":value??0}</strong><small>{detail}</small></article>}
function Finance({label,value}:{label:string;value?:string}){return <article><span>{label}</span><strong>{value||"0.00000000"}</strong><small>USDT</small></article>}
