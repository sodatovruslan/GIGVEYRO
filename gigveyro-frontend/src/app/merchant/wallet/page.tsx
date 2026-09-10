"use client";

import { useTranslations } from "next-intl";

import { BalanceCard, PageHeading } from "@/app/user/user-components";
import { useAppFormat } from "@/features/i18n/use-app-format";
import { useEnumLabels } from "@/features/i18n/use-enum-labels";
import { merchantApi } from "@/lib/api/merchant";
import { useApiQuery } from "@/lib/hooks/use-api-query";

import styles from "../../user/user.module.css";

export default function MerchantWalletPage() {
  const t = useTranslations("wallet");
  const dashboard = useTranslations("dashboard");
  const common = useTranslations("common");
  const format = useAppFormat();
  const labels = useEnumLabels();
  const wallet = useApiQuery(merchantApi.wallet, "merchant-wallet");
  const ledger = useApiQuery(merchantApi.ledger, "merchant-ledger");
  const fee = useApiQuery(merchantApi.fee, "merchant-fee");
  return <section><PageHeading eyebrow={dashboard("merchantFinanceEyebrow")} title={t("title")} text={t("merchantSubtitle")} />
    <div className={styles.balanceGrid}><BalanceCard label={t("available")} value={wallet.data?.available_balance} loading={wallet.loading} accent /><BalanceCard label={t("held")} value={wallet.data?.held_balance} loading={wallet.loading} /></div>
    {wallet.error && <div className={styles.inlineError}>{wallet.error}</div>}
    {fee.data && <div className={styles.contentCard} style={{ marginTop: 14 }}>
      <div className={styles.contentHeader}><h2>{t("feeTitle")}</h2></div>
      <p>{fee.data.enabled && fee.data.supported_for_charging
        ? t("feePercent", { percent: (fee.data.percent_bps / 100).toString(), fixed: fee.data.fixed_fee })
        : t("feeNotCharged")}</p>
    </div>}
    <div className={styles.contentCard} style={{ marginTop: 14 }}><div className={styles.contentHeader}><h2>{t("history")}</h2><button onClick={ledger.refetch}>{common("refresh")}</button></div>{ledger.loading ? <div className={styles.state}>{t("loadingOperations")}</div> : ledger.error ? <div className={`${styles.state} ${styles.errorText}`}>{ledger.error}</div> : !ledger.data?.items.length ? <div className={styles.state}>{t("noOperations")}</div> : <div className={styles.tableScroll}><table><thead><tr><th>{common("date")}</th><th>{common("type")}</th><th>{common("description")}</th><th>{common("amount")}</th><th>{t("availableAfter")}</th></tr></thead><tbody>{ledger.data.items.map((entry) => <tr key={entry.id}><td>{format.dateTime(entry.created_at)}</td><td>{labels.ledger(entry.type)}</td><td>{entry.description || "—"}</td><td className={Number(entry.amount) >= 0 ? styles.positive : styles.negative}>{entry.amount} {entry.currency.toUpperCase()}</td><td>{entry.available_after} USDT</td></tr>)}</tbody></table></div>}</div>
  </section>;
}
