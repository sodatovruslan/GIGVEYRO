"use client";

import { userApi } from "@/lib/api/user";
import { useApiQuery } from "@/lib/hooks/use-api-query";

import { BalanceCard, PageHeading } from "../user-components";
import styles from "../user.module.css";

export default function UserWalletPage() {
  const wallet = useApiQuery(userApi.wallet, "wallet-page");
  const ledger = useApiQuery(userApi.ledger, "ledger-page");
  return <section>
    <PageHeading eyebrow="WALLET" title="Баланс" text="Состояние кошелька и история операций из Backend V1" />
    <div className={styles.balanceGrid}>
      <BalanceCard label="Доступный баланс" value={wallet.data?.available_balance} loading={wallet.loading} accent />
      <BalanceCard label="Заморожено" value={wallet.data?.frozen_balance} loading={wallet.loading} />
      <BalanceCard label="Insurance" value={wallet.data?.insurance_balance} loading={wallet.loading} />
    </div>
    {wallet.error && <div className={styles.inlineError}>{wallet.error}</div>}
    <div className={styles.contentCard} style={{ marginTop: 14 }}>
      <div className={styles.contentHeader}><h2>История операций</h2><button onClick={ledger.refetch}>Обновить</button></div>
      {ledger.loading ? <div className={styles.state}>Загружаем операции…</div> : ledger.error ? <div className={`${styles.state} ${styles.errorText}`}>{ledger.error}</div> : !ledger.data?.items.length ? <div className={styles.state}>Операций пока нет</div> : <div className={styles.tableScroll}><table><thead><tr><th>Дата</th><th>Тип</th><th>Описание</th><th>Сумма</th><th>Баланс после</th></tr></thead><tbody>{ledger.data.items.map((entry) => <tr key={entry.id}><td>{new Intl.DateTimeFormat("ru-RU", { dateStyle: "short", timeStyle: "short" }).format(new Date(entry.created_at))}</td><td>{entry.type}</td><td>{entry.description || "—"}</td><td className={Number(entry.amount) >= 0 ? styles.positive : styles.negative}>{Number(entry.amount) >= 0 ? "+" : ""}{entry.amount} {entry.currency.toUpperCase()}</td><td>{entry.available_after} USDT</td></tr>)}</tbody></table></div>}
    </div>
  </section>;
}
