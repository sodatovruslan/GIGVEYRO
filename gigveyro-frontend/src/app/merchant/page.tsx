"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { BalanceCard, PageHeading } from "@/app/user/user-components";
import { merchantApi } from "@/lib/api/merchant";
import { useApiQuery } from "@/lib/hooks/use-api-query";

import styles from "../user/user.module.css";

export default function MerchantDashboard() {
  const t = useTranslations("dashboard");
  const wallet = useApiQuery(merchantApi.wallet, "merchant-dashboard-wallet");
  const withdrawals = useApiQuery(merchantApi.withdrawals, "merchant-dashboard-withdrawals");
  return <section>
    <PageHeading eyebrow={t("merchantEyebrow")} title={t("merchantTitle")} text={t("merchantSubtitle")} />
    <div className={styles.balanceGrid}>
      <BalanceCard label={t("availableBalance")} value={wallet.data?.available_balance} loading={wallet.loading} accent />
      <BalanceCard label={t("held")} value={wallet.data?.held_balance} loading={wallet.loading} />
      <article className={styles.balanceCard}><span>{t("withdrawalRequests")}</span><div><strong>{withdrawals.loading ? "—" : withdrawals.data?.items.filter((item) => item.status === "pending").length || 0}</strong><small>{t("processing")}</small></div></article>
    </div>
    {(wallet.error || withdrawals.error) && <div className={styles.inlineError}>{wallet.error || withdrawals.error}</div>}
    <div className={styles.dashboardGrid}>
      <article className={styles.trafficCard}><div className={styles.cardHeading}><div><span>{t("dealsEyebrow")}</span><h2>{t("tradingOperations")}</h2></div><Link href="/merchant/deals">{t("open")}</Link></div><p>{t("tradingText")}</p></article>
      <article className={styles.requisiteSummary}><div className={styles.cardHeading}><div><span>{t("payoutsEyebrow")}</span><h2>{t("payouts")}</h2></div><Link href="/merchant/withdrawals">{t("manage")}</Link></div><div className={styles.bigNumber}>{withdrawals.data?.total || 0}<small>{t("allRequests")}</small></div></article>
    </div>
  </section>;
}
