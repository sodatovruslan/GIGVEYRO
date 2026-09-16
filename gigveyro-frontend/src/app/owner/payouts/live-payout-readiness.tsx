"use client";

import { FormEvent, useState } from "react";
import { useTranslations } from "next-intl";

import { useAppFormat } from "@/features/i18n/use-app-format";
import { useLocalizedError } from "@/features/i18n/use-localized-error";
import { ownerOperationsApi } from "@/lib/api/owner-operations";
import { useApiQuery } from "@/lib/hooks/use-api-query";

import styles from "./payouts.module.css";
import liveStyles from "./live-payout-readiness.module.css";

const readinessChecks = [
  "global_payout_enabled",
  "provider_live",
  "write_credentials_configured",
  "write_permission_verified",
  "ip_whitelist_verified",
  "address_allowlist_configured",
  "network_allowlist_configured",
  "dual_approval_ready",
  "reconciliation_ready",
] as const;

export function LivePayoutReadinessPanel() {
  const t = useTranslations("payouts.live");
  const common = useTranslations("common");
  const format = useAppFormat();
  const localizeError = useLocalizedError();
  const readiness = useApiQuery(ownerOperationsApi.payoutReadiness, "payout-readiness");
  const addresses = useApiQuery(ownerOperationsApi.payoutAddresses, "payout-addresses");
  const networks = useApiQuery(ownerOperationsApi.payoutNetworks, "payout-networks");
  const [beneficiaryAccountId, setBeneficiaryAccountId] = useState("");
  const [label, setLabel] = useState("");
  const [address, setAddress] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function createAddress(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await ownerOperationsApi.createPayoutAddress({ beneficiary_account_id: beneficiaryAccountId, label, address, asset: "USDT", network: "TRC20" });
      setBeneficiaryAccountId("");
      setLabel("");
      setAddress("");
      await Promise.all([addresses.refetch(), readiness.refetch()]);
    } catch (caught) {
      setError(localizeError(caught));
    } finally {
      setBusy(false);
    }
  }

  async function disableAddress(id: string) {
    setBusy(true);
    setError("");
    try {
      await ownerOperationsApi.disablePayoutAddress(id);
      await Promise.all([addresses.refetch(), readiness.refetch()]);
    } catch (caught) {
      setError(localizeError(caught));
    } finally {
      setBusy(false);
    }
  }

  const loading = readiness.loading || addresses.loading || networks.loading;
  const queryError = readiness.error || addresses.error || networks.error;

  return (
    <article className={liveStyles.panel}>
      <header className={liveStyles.header}>
        <div><span>{t("eyebrow")}</span><h2>{t("title")}</h2></div>
        <strong data-ready={readiness.data?.ready || false}>
          {readiness.data?.ready ? t("ready") : t("notReady")}
        </strong>
      </header>
      <p>{t("description")}</p>
      {(error || queryError) && <div className={styles.error}>{error || queryError}</div>}
      {loading ? <div className={styles.state}>{common("loading")}</div> : <>
        <div className={liveStyles.readinessGrid}>
          {readinessChecks.map((check) => {
            const passed = readiness.data?.checks[check] === true;
            return <div key={check}><span>{t(`checks.${check}`)}</span><strong data-passed={passed}>{passed ? common("yes") : common("no")}</strong></div>;
          })}
        </div>
        <section className={liveStyles.allowlist}>
          <div className={liveStyles.allowlistHeading}><div><h3>{t("addresses")}</h3><p>{t("addressesHint")}</p></div></div>
          <form onSubmit={(event) => void createAddress(event)} className={liveStyles.addressForm}>
            <label><span>{t("beneficiaryAccountId")}</span><input required maxLength={36} autoComplete="off" spellCheck={false} placeholder={t("beneficiaryAccountIdHint")} value={beneficiaryAccountId} onChange={(event) => setBeneficiaryAccountId(event.target.value)} /></label>
            <label><span>{t("label")}</span><input required maxLength={100} value={label} onChange={(event) => setLabel(event.target.value)} /></label>
            <label><span>{t("address")}</span><input required maxLength={255} autoComplete="off" spellCheck={false} value={address} onChange={(event) => setAddress(event.target.value)} /></label>
            <div><span>{t("binding")}</span><strong>USDT · TRC20</strong></div>
            <button disabled={busy || !beneficiaryAccountId.trim() || !label.trim() || !address.trim()}>{t("addAddress")}</button>
          </form>
          <div className={liveStyles.addressList}>
            {!addresses.data?.length ? <span>{t("noAddresses")}</span> : addresses.data.map((item) => <div key={item.id}>
              <div><strong>{item.label}</strong><small>{item.asset} · {item.network} · {item.masked_address}</small><small>{t("beneficiary")}: {item.beneficiary_account_id}</small><small>{format.dateTime(item.created_at)}</small></div>
              <span data-enabled={item.enabled}>{item.enabled ? t("enabled") : t("disabled")}</span>
              {item.enabled && <button disabled={busy} onClick={() => void disableAddress(item.id)}>{t("disable")}</button>}
            </div>)}
          </div>
        </section>
        <section className={liveStyles.networkList}>
          <h3>{t("networks")}</h3>
          {!networks.data?.length ? <span>{t("noNetworks")}</span> : networks.data.map((item) => <div key={item.id}><strong>{item.asset} · {item.network}</strong><span data-enabled={item.enabled}>{item.enabled ? t("enabled") : t("disabled")}</span></div>)}
        </section>
      </>}
      <footer>{t("noLiveAction")}</footer>
    </article>
  );
}
