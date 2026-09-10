"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { BalanceCard, PageHeading } from "@/app/user/user-components";
import { useLocalizedError } from "@/features/i18n/use-localized-error";
import { downloadMerchantInvoicesCsv, merchantApi } from "@/lib/api/merchant";
import { useApiQuery } from "@/lib/hooks/use-api-query";

import styles from "../../user/user.module.css";

export default function MerchantStatisticsPage() {
  const t = useTranslations("merchantStatistics");
  const localizeError = useLocalizedError();
  const query = useApiQuery(merchantApi.statistics, "merchant-statistics");
  const [exportError, setExportError] = useState("");
  const [exporting, setExporting] = useState(false);

  async function exportCsv() {
    setExportError(""); setExporting(true);
    try { await downloadMerchantInvoicesCsv(); }
    catch (reason) { setExportError(t("exportFailed") || localizeError(reason)); }
    finally { setExporting(false); }
  }

  return <section>
    <PageHeading eyebrow={t("eyebrow")} title={t("title")} text={t("subtitle")} />
    {query.loading ? <div className={styles.state}>{t("loading")}</div>
      : query.error ? <div className={`${styles.state} ${styles.errorText}`}>{query.error}</div>
      : query.data && <>
          <h2>{t("invoicesTitle")}</h2>
          <div className={styles.balanceGrid}>
            <BalanceCard label={t("total")} value={String(query.data.invoices.total)} loading={false} accent />
            <BalanceCard label={t("pendingPayment")} value={String(query.data.invoices.pending_payment)} loading={false} />
            <BalanceCard label={t("paid")} value={String(query.data.invoices.paid)} loading={false} />
            <BalanceCard label={t("paidVolume")} value={query.data.invoices.paid_volume} loading={false} />
          </div>
          <h2 style={{ marginTop: 24 }}>{t("withdrawalsTitle")}</h2>
          <div className={styles.balanceGrid}>
            <BalanceCard label={t("total")} value={String(query.data.withdrawals.total)} loading={false} accent />
            <BalanceCard label={t("pending")} value={String(query.data.withdrawals.pending)} loading={false} />
            <BalanceCard label={t("paid")} value={String(query.data.withdrawals.paid)} loading={false} />
            <BalanceCard label={t("paidVolume")} value={query.data.withdrawals.paid_volume} loading={false} />
          </div>
        </>}
    <div className={styles.contentCard} style={{ marginTop: 24 }}>
      <div className={styles.contentHeader}><h2>{t("reportsTitle")}</h2></div>
      <p>{t("reportsSubtitle")}</p>
      {exportError && <div className={styles.inlineError}>{exportError}</div>}
      <button onClick={() => void exportCsv()} disabled={exporting}>{t("exportCsv")}</button>
    </div>
  </section>;
}
