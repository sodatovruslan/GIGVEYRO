"use client";

import { useTranslations } from "next-intl";

import { useAppFormat } from "@/features/i18n/use-app-format";
import { useEnumLabels } from "@/features/i18n/use-enum-labels";
import { userApi } from "@/lib/api/user";
import { useApiQuery } from "@/lib/hooks/use-api-query";

import { BalanceCard, PageHeading } from "../user-components";
import styles from "../user.module.css";

export default function UserWalletPage() {
  const t = useTranslations("wallet");
  const common = useTranslations("common");
  const format = useAppFormat();
  const labels = useEnumLabels();
  const wallet = useApiQuery(userApi.wallet, "wallet-page");
  const ledger = useApiQuery(userApi.ledger, "ledger-page");
  return <section>
    <PageHeading eyebrow={t("eyebrow")} title={t("title")} text={t("userSubtitle")} />
    <div className={styles.balanceGrid}><BalanceCard label={t("available")} value={wallet.data?.available_balance} loading={wallet.loading} accent /><BalanceCard label={t("frozen")} value={wallet.data?.frozen_balance} loading={wallet.loading} /><BalanceCard label={t("insurance")} value={wallet.data?.insurance_balance} loading={wallet.loading} /></div>
    {wallet.error && <div className={styles.inlineError}>{wallet.error}</div>}
    <div className={styles.contentCard} style={{ marginTop: 14 }}><div className={styles.contentHeader}><h2>{t("history")}</h2><button onClick={ledger.refetch}>{common("refresh")}</button></div>
      {ledger.loading ? <div className={styles.state}>{t("loadingOperations")}</div> : ledger.error ? <div className={`${styles.state} ${styles.errorText}`}>{ledger.error}</div> : !ledger.data?.items.length ? <div className={styles.state}>{t("noOperations")}</div> : <div className={styles.tableScroll}><table><thead><tr><th>{common("date")}</th><th>{common("type")}</th><th>{common("description")}</th><th>{common("amount")}</th><th>{t("balanceAfter")}</th></tr></thead><tbody>{ledger.data.items.map((entry) => <tr key={entry.id}><td>{format.dateTime(entry.created_at)}</td><td>{labels.ledger(entry.type)}</td><td>{entry.description || "—"}</td><td className={Number(entry.amount) >= 0 ? styles.positive : styles.negative}>{Number(entry.amount) >= 0 ? "+" : ""}{entry.amount} {entry.currency.toUpperCase()}</td><td>{entry.available_after} USDT</td></tr>)}</tbody></table></div>}
    </div>
  </section>;
}
