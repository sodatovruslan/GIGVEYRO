"use client";

import { BalanceCard, PageHeading } from "@/app/user/user-components";
import { merchantApi } from "@/lib/api/merchant";
import { useApiQuery } from "@/lib/hooks/use-api-query";

import styles from "../../user/user.module.css";

export default function MerchantWalletPage() {
  const wallet = useApiQuery(merchantApi.wallet, "merchant-wallet");
  const ledger = useApiQuery(merchantApi.ledger, "merchant-ledger");
  return <section><PageHeading eyebrow="MERCHANT FINANCE" title="Баланс" text="Кошелёк и история расчётов" />
    <div className={styles.balanceGrid}><BalanceCard label="Доступный баланс" value={wallet.data?.available_balance} loading={wallet.loading} accent /><BalanceCard label="Удерживается" value={wallet.data?.held_balance} loading={wallet.loading} /></div>
    {wallet.error && <div className={styles.inlineError}>{wallet.error}</div>}
    <div className={styles.contentCard} style={{ marginTop: 14 }}><div className={styles.contentHeader}><h2>История операций</h2><button onClick={ledger.refetch}>Обновить</button></div>{ledger.loading ? <div className={styles.state}>Загрузка…</div> : ledger.error ? <div className={`${styles.state} ${styles.errorText}`}>{ledger.error}</div> : !ledger.data?.items.length ? <div className={styles.state}>Операций пока нет</div> : <div className={styles.tableScroll}><table><thead><tr><th>Дата</th><th>Тип</th><th>Описание</th><th>Сумма</th><th>Доступно после</th></tr></thead><tbody>{ledger.data.items.map((entry) => <tr key={entry.id}><td>{new Intl.DateTimeFormat("ru-RU", { dateStyle: "short", timeStyle: "short" }).format(new Date(entry.created_at))}</td><td>{entry.type}</td><td>{entry.description || "—"}</td><td className={Number(entry.amount) >= 0 ? styles.positive : styles.negative}>{entry.amount} {entry.currency.toUpperCase()}</td><td>{entry.available_after} USDT</td></tr>)}</tbody></table></div>}</div>
  </section>;
}
