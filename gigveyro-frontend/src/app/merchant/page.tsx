"use client";

import Link from "next/link";

import { merchantApi } from "@/lib/api/merchant";
import { useApiQuery } from "@/lib/hooks/use-api-query";
import { BalanceCard, PageHeading } from "@/app/user/user-components";

import styles from "../user/user.module.css";

export default function MerchantDashboard() {
  const wallet = useApiQuery(merchantApi.wallet, "merchant-dashboard-wallet");
  const withdrawals = useApiQuery(merchantApi.withdrawals, "merchant-dashboard-withdrawals");
  return <section>
    <PageHeading eyebrow="MERCHANT WORKSPACE" title="Кабинет мерчанта" text="Контроль расчётов, сделок и вывода средств" />
    <div className={styles.balanceGrid}>
      <BalanceCard label="Доступный баланс" value={wallet.data?.available_balance} loading={wallet.loading} accent />
      <BalanceCard label="Удерживается" value={wallet.data?.held_balance} loading={wallet.loading} />
      <article className={styles.balanceCard}><span>ЗАЯВКИ НА ВЫВОД</span><div><strong>{withdrawals.loading ? "—" : withdrawals.data?.items.filter((item) => item.status === "pending").length || 0}</strong><small>в обработке</small></div></article>
    </div>
    {(wallet.error || withdrawals.error) && <div className={styles.inlineError}>{wallet.error || withdrawals.error}</div>}
    <div className={styles.dashboardGrid}>
      <article className={styles.trafficCard}><div className={styles.cardHeading}><div><span>DEALS</span><h2>Торговые операции</h2></div><Link href="/merchant/deals">Открыть →</Link></div><p>Создавайте заявки в TJS. Курс и итоговую сумму USDT рассчитывает Backend V1.</p></article>
      <article className={styles.requisiteSummary}><div className={styles.cardHeading}><div><span>PAYOUTS</span><h2>Вывод средств</h2></div><Link href="/merchant/withdrawals">Управлять →</Link></div><div className={styles.bigNumber}>{withdrawals.data?.total || 0}<small>всего заявок</small></div></article>
    </div>
  </section>;
}
