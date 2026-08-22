"use client";

import Link from "next/link";
import { useState } from "react";
import { useTranslations } from "next-intl";

import { useLocalizedError } from "@/features/i18n/use-localized-error";
import { userApi } from "@/lib/api/user";
import { useApiQuery } from "@/lib/hooks/use-api-query";

import { BalanceCard, PageHeading } from "./user-components";
import styles from "./user.module.css";

export default function UserDashboard() {
  const dashboard = useTranslations("dashboard");
  const trafficText = useTranslations("traffic");
  const requisitesText = useTranslations("requisites");
  const localizeError = useLocalizedError();
  const wallet = useApiQuery(userApi.wallet, "user-wallet");
  const requisites = useApiQuery(userApi.requisites, "user-requisites-summary");
  const traffic = useApiQuery(userApi.traffic, "user-traffic");
  const [toggleError, setToggleError] = useState("");
  const [toggling, setToggling] = useState(false);

  async function toggleTraffic() {
    if (!traffic.data) return;
    setToggling(true); setToggleError("");
    try { await userApi.setTraffic(!traffic.data.is_enabled); await traffic.refetch(); }
    catch (reason) { setToggleError(localizeError(reason)); }
    finally { setToggling(false); }
  }

  return <section>
    <PageHeading eyebrow={dashboard("userEyebrow")} title={dashboard("userTitle")} text={dashboard("userSubtitle")} />
    <div className={styles.balanceGrid}>
      <BalanceCard label={dashboard("availableBalance")} value={wallet.data?.available_balance} loading={wallet.loading} accent />
      <BalanceCard label={dashboard("frozen")} value={wallet.data?.frozen_balance} loading={wallet.loading} />
      <BalanceCard label={dashboard("insurance")} value={wallet.data?.insurance_balance} loading={wallet.loading} />
    </div>
    {wallet.error && <div className={styles.inlineError}>{wallet.error}</div>}
    <div className={styles.dashboardGrid}>
      <article className={styles.trafficCard}>
        <div className={styles.cardHeading}><div><span>{trafficText("eyebrow")}</span><h2>{trafficText("title")}</h2></div><button className={`${styles.toggle} ${traffic.data?.is_enabled ? styles.toggleOn : ""}`} disabled={traffic.loading || toggling} onClick={toggleTraffic} aria-label={trafficText("toggle")}><i /></button></div>
        {traffic.loading ? <p>{trafficText("checking")}</p> : traffic.error ? <p className={styles.errorText}>{traffic.error}</p> : <><strong className={traffic.data?.is_enabled ? styles.enabled : styles.disabled}><i />{traffic.data?.is_enabled ? trafficText("enabled") : trafficText("disabled")}</strong><p>{traffic.data?.is_enabled ? trafficText("enabledText") : trafficText("disabledText")}</p></>}
        {toggleError && <p className={styles.errorText}>{toggleError}</p>}
      </article>
      <article className={styles.requisiteSummary}>
        <div className={styles.cardHeading}><div><span>{requisitesText("eyebrow")}</span><h2>{requisitesText("title")}</h2></div><Link href="/user/requisites">{dashboard("manage")}</Link></div>
        {requisites.loading ? <p>{dashboard("loading")}</p> : requisites.error ? <p className={styles.errorText}>{requisites.error}</p> : <div className={styles.bigNumber}>{requisites.data?.filter((item) => item.is_active && !item.is_archived).length || 0}<small>{requisitesText("activeCards")}</small></div>}
      </article>
    </div>
  </section>;
}
