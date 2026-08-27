"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { useAppFormat } from "@/features/i18n/use-app-format";
import { userApi } from "@/lib/api/user";
import { useApiQuery } from "@/lib/hooks/use-api-query";
import { Pager } from "@/components/ui/pager";

import styles from "../user.module.css";

export function FiatWalletSection() {
  const t = useTranslations("fiatWallets");
  const common = useTranslations("common");
  const format = useAppFormat();
  const balances = useApiQuery(userApi.fiatBalances, "user-fiat:balances");
  const [historyOffset, setHistoryOffset] = useState(0);
  const [ledgerOffset, setLedgerOffset] = useState(0);
  const history = useApiQuery(() => userApi.fiatConversions(historyOffset), `user-fiat:history:${historyOffset}`);
  const ledger = useApiQuery(() => userApi.fiatLedger(ledgerOffset), `user-fiat:ledger:${ledgerOffset}`);

  return <section className={styles.fiatSection}>
    <div className={styles.fiatHeading}><div><span>{t("eyebrow")}</span><h2>{t("title")}</h2><p>{t("subtitle")}</p></div></div>
    <div className={styles.balanceGrid}>
      {balances.loading ? <div className={styles.state}>{common("loading")}</div> : balances.error ? <div className={`${styles.state} ${styles.errorText}`}>{balances.error}</div> : balances.data?.items.map((item) => <article className={styles.balanceCard} key={item.currency}><span>{t("balance", { currency: item.currency })}</span><div><strong className={styles.accent}>{format.number(item.available, 8)}</strong><small>{item.currency}</small></div></article>)}
    </div>
    <div className={styles.managedHint}>{t("userManagedHint")}</div>
    <div className={styles.contentCard}><div className={styles.contentHeader}><h2>{t("conversionHistory")}</h2><button onClick={history.refetch}>{common("refresh")}</button></div>
      {history.loading ? <div className={styles.state}>{common("loading")}</div> : history.error ? <div className={`${styles.state} ${styles.errorText}`}>{history.error}</div> : !history.data?.items.length ? <div className={styles.state}>{t("noConversions")}</div> : <><div className={styles.tableScroll}><table><thead><tr><th>{common("date")}</th><th>{t("from")}</th><th>{t("to")}</th><th>{t("rate")}</th><th>{t("provider")}</th></tr></thead><tbody>{history.data.items.map((item) => <tr key={item.id}><td>{format.dateTime(item.created_at)}</td><td>{format.number(item.source_amount, 8)} {item.from_currency}</td><td>{format.number(item.destination_amount, 8)} {item.to_currency}</td><td>{format.number(item.exchange_rate, 8)}</td><td>{item.rate_provider}</td></tr>)}</tbody></table></div><Pager offset={historyOffset} limit={history.data.limit} itemCount={history.data.items.length} total={history.data.total} onPage={setHistoryOffset} /></>}
    </div>
    <div className={styles.contentCard}><div className={styles.contentHeader}><h2>{t("operations")}</h2><button onClick={ledger.refetch}>{common("refresh")}</button></div>
      {ledger.loading ? <div className={styles.state}>{common("loading")}</div> : ledger.error ? <div className={`${styles.state} ${styles.errorText}`}>{ledger.error}</div> : !ledger.data?.items.length ? <div className={styles.state}>{t("noOperations")}</div> : <><div className={styles.tableScroll}><table><thead><tr><th>{common("date")}</th><th>{common("type")}</th><th>{common("amount")}</th><th>{t("balanceAfter")}</th></tr></thead><tbody>{ledger.data.items.map((item) => <tr key={item.id}><td>{format.dateTime(item.created_at)}</td><td>{t(`ledgerTypes.${item.type}`)}</td><td className={Number(item.amount) >= 0 ? styles.positive : styles.negative}>{Number(item.amount) >= 0 ? "+" : ""}{format.number(item.amount, 8)} {item.currency}</td><td>{format.number(item.balance_after, 8)} {item.currency}</td></tr>)}</tbody></table></div><Pager offset={ledgerOffset} limit={ledger.data.limit} itemCount={ledger.data.items.length} total={ledger.data.total} onPage={setLedgerOffset} /></>}
    </div>
  </section>;
}
