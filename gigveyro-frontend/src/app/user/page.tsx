"use client";

import Link from "next/link";
import { useState } from "react";

import { ApiError } from "@/lib/api/error";
import { userApi } from "@/lib/api/user";
import { useApiQuery } from "@/lib/hooks/use-api-query";

import styles from "./user.module.css";
import { BalanceCard, PageHeading } from "./user-components";

export default function UserDashboard() {
  const wallet = useApiQuery(userApi.wallet, "user-wallet");
  const requisites = useApiQuery(userApi.requisites, "user-requisites-summary");
  const traffic = useApiQuery(userApi.traffic, "user-traffic");
  const [toggleError, setToggleError] = useState("");
  const [toggling, setToggling] = useState(false);

  async function toggleTraffic() {
    if (!traffic.data) return;
    setToggling(true); setToggleError("");
    try { await userApi.setTraffic(!traffic.data.is_enabled); await traffic.refetch(); }
    catch (reason) { setToggleError(reason instanceof ApiError ? reason.message : "Не удалось изменить состояние трафика."); }
    finally { setToggling(false); }
  }

  return <section>
    <PageHeading eyebrow="PERSONAL WORKSPACE" title="Главная" text="Баланс, реквизиты и доступ к сделкам" />
    <div className={styles.balanceGrid}>
      <BalanceCard label="Доступный баланс" value={wallet.data?.available_balance} loading={wallet.loading} accent />
      <BalanceCard label="Заморожено" value={wallet.data?.frozen_balance} loading={wallet.loading} />
      <BalanceCard label="Insurance" value={wallet.data?.insurance_balance} loading={wallet.loading} />
    </div>
    {wallet.error && <div className={styles.inlineError}>{wallet.error}</div>}
    <div className={styles.dashboardGrid}>
      <article className={styles.trafficCard}>
        <div className={styles.cardHeading}><div><span>TRAFFIC CONTROL</span><h2>Приём трафика</h2></div><button className={`${styles.toggle} ${traffic.data?.is_enabled ? styles.toggleOn : ""}`} disabled={traffic.loading || toggling} onClick={toggleTraffic} aria-label="Переключить трафик"><i /></button></div>
        {traffic.loading ? <p>Проверяем состояние…</p> : traffic.error ? <p className={styles.errorText}>{traffic.error}</p> : <><strong className={traffic.data?.is_enabled ? styles.enabled : styles.disabled}><i />{traffic.data?.is_enabled ? "Трафик включён" : "Трафик выключен"}</strong><p>{traffic.data?.is_enabled ? "Активные реквизиты участвуют в распределении сделок." : "Новые сделки сейчас не будут назначаться."}</p></>}
        {toggleError && <p className={styles.errorText}>{toggleError}</p>}
      </article>
      <article className={styles.requisiteSummary}>
        <div className={styles.cardHeading}><div><span>REQUISITES</span><h2>Банковские реквизиты</h2></div><Link href="/user/requisites">Управлять →</Link></div>
        {requisites.loading ? <p>Загрузка…</p> : requisites.error ? <p className={styles.errorText}>{requisites.error}</p> : <div className={styles.bigNumber}>{requisites.data?.filter((item) => item.is_active && !item.is_archived).length || 0}<small>активных</small></div>}
      </article>
    </div>
  </section>;
}
