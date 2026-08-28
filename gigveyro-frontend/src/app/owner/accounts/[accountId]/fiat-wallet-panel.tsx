"use client";

import { Pager } from "@/components/ui/pager";
import { useAppFormat } from "@/features/i18n/use-app-format";
import { useLocalizedError } from "@/features/i18n/use-localized-error";
import { ownerAccountsApi } from "@/lib/api/owner-accounts";
import type { FiatConversionPreview, FiatCurrency } from "@/lib/api/types";
import { useApiQuery } from "@/lib/hooks/use-api-query";
import { useTranslations } from "next-intl";
import { type FormEvent, useEffect, useState } from "react";

import styles from "./account.module.css";

type Modal = "allocate" | "convert" | null;

export function FiatWalletPanel({ accountId }: { accountId: string }) {
  const t = useTranslations("fiatWallets");
  const common = useTranslations("common");
  const format = useAppFormat();
  const localizeError = useLocalizedError();
  const balances = useApiQuery(
    () => ownerAccountsApi.fiatBalances(accountId),
    `owner-fiat:balances:${accountId}`,
  );
  const [ledgerOffset, setLedgerOffset] = useState(0);
  const [historyOffset, setHistoryOffset] = useState(0);
  const ledger = useApiQuery(
    () => ownerAccountsApi.fiatLedger(accountId, ledgerOffset),
    `owner-fiat:ledger:${accountId}:${ledgerOffset}`,
  );
  const history = useApiQuery(
    () => ownerAccountsApi.fiatConversions(accountId, historyOffset),
    `owner-fiat:history:${accountId}:${historyOffset}`,
  );
  const [modal, setModal] = useState<Modal>(null);
  const [currency, setCurrency] = useState<FiatCurrency>("TJS");
  const [fromCurrency, setFromCurrency] = useState<FiatCurrency>("TJS");
  const [amount, setAmount] = useState("");
  const [comment, setComment] = useState("");
  const [idempotencyKey, setIdempotencyKey] = useState("");
  const [preview, setPreview] = useState<FiatConversionPreview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const toCurrency: FiatCurrency = fromCurrency === "TJS" ? "RUB" : "TJS";

  useEffect(() => {
    if (modal !== "convert" || !amount || Number(amount) <= 0) return;
    let active = true;
    const timeout = window.setTimeout(async () => {
      setPreviewing(true);
      setError("");
      try {
        const result = await ownerAccountsApi.previewFiatConversion(
          fromCurrency,
          toCurrency,
          amount,
        );
        if (active) setPreview(result);
      } catch (reason) {
        if (active) setError(localizeError(reason));
      } finally {
        if (active) setPreviewing(false);
      }
    }, 300);
    return () => {
      active = false;
      window.clearTimeout(timeout);
    };
  }, [amount, fromCurrency, localizeError, modal, toCurrency]);

  function open(next: Exclude<Modal, null>) {
    setModal(next);
    setAmount("");
    setComment("");
    setError("");
    setPreview(null);
    setIdempotencyKey(crypto.randomUUID());
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      if (modal === "allocate") {
        await ownerAccountsApi.allocateFiat(
          accountId,
          currency,
          amount,
          comment,
          idempotencyKey,
        );
        setSuccess(t("allocated"));
      } else if (modal === "convert") {
        const result = await ownerAccountsApi.convertFiat(
          accountId,
          fromCurrency,
          toCurrency,
          amount,
          comment,
          idempotencyKey,
        );
        setSuccess(
          Number(result.fee_amount) > 0
            ? t("convertedWithFee", {
                amount: format.number(result.destination_amount, 8),
                currency: result.to_currency,
                fee: format.number(result.fee_amount, 8),
              })
            : t("convertedResult", {
                amount: format.number(result.destination_amount, 8),
                currency: result.to_currency,
              }),
        );
      }
      setModal(null);
      await Promise.all([balances.refetch(), ledger.refetch(), history.refetch()]);
    } catch (reason) {
      setError(localizeError(reason));
    } finally {
      setSaving(false);
    }
  }

  return <>
    <div className={styles.sectionTitle}>
      <div><span>{t("eyebrow")}</span><h2>{t("title")}</h2></div>
      <div className={styles.walletActions}>
        <button onClick={() => open("allocate")}>{t("allocate")}</button>
        <button onClick={() => open("convert")}>{t("convert")}</button>
      </div>
    </div>
    {success && <div className={styles.fiatNotice}>{success}</div>}
    <div className={styles.walletGrid}>
      {balances.loading ? <div className={styles.walletState}>{common("loading")}</div>
        : balances.error ? <div className={`${styles.walletState} ${styles.error}`}>{balances.error}</div>
        : balances.data?.items.map((item) => <article className={styles.walletCard} key={item.currency}><span>{t("balance", { currency: item.currency })}</span><strong className={styles.accent}>{format.number(item.available, 8)}</strong><small>{item.currency}</small></article>)}
    </div>
    <div className={styles.managedHint}>{t("ownerManagedHint")}</div>
    <div className={styles.ledgerCard}>
      <div className={styles.ledgerHeader}><div><span>{t("historyEyebrow")}</span><h2>{t("conversionHistory")}</h2></div><button onClick={history.refetch}>{common("refresh")}</button></div>
      {history.loading ? <div className={styles.ledgerState}>{common("loading")}</div>
        : history.error ? <div className={`${styles.ledgerState} ${styles.error}`}>{history.error}</div>
        : !history.data?.items.length ? <div className={styles.ledgerState}>{t("noConversions")}</div>
        : <><div className={styles.tableScroll}><table><thead><tr><th>{common("date")}</th><th>{t("from")}</th><th>{t("to")}</th><th>{t("rate")}</th><th>{t("provider")}</th></tr></thead><tbody>{history.data.items.map((item) => <tr key={item.id}><td>{format.dateTime(item.created_at)}</td><td>{format.number(item.source_amount, 8)} {item.from_currency}</td><td>{format.number(item.destination_amount, 8)} {item.to_currency}{Number(item.fee_amount) > 0 && <small className={styles.feeLine}>{t("fee")}: {format.number(item.fee_amount, 8)} {item.to_currency}</small>}</td><td>{format.number(item.effective_rate, 8)}</td><td>{item.rate_provider}</td></tr>)}</tbody></table></div><Pager offset={historyOffset} limit={history.data.limit} itemCount={history.data.items.length} total={history.data.total} onPage={setHistoryOffset} /></>}
    </div>
    <div className={styles.ledgerCard} style={{ marginTop: 13 }}>
      <div className={styles.ledgerHeader}><div><span>{t("ledgerEyebrow")}</span><h2>{t("operations")}</h2></div><button onClick={ledger.refetch}>{common("refresh")}</button></div>
      {ledger.loading ? <div className={styles.ledgerState}>{common("loading")}</div>
        : ledger.error ? <div className={`${styles.ledgerState} ${styles.error}`}>{ledger.error}</div>
        : !ledger.data?.items.length ? <div className={styles.ledgerState}>{t("noOperations")}</div>
        : <><div className={styles.tableScroll}><table><thead><tr><th>{common("date")}</th><th>{common("type")}</th><th>{common("amount")}</th><th>{t("balanceAfter")}</th></tr></thead><tbody>{ledger.data.items.map((item) => <tr key={item.id}><td>{format.dateTime(item.created_at)}</td><td>{t(`ledgerTypes.${item.type}`)}</td><td className={Number(item.amount) >= 0 ? styles.positive : styles.negative}>{format.number(item.amount, 8)} {item.currency}</td><td>{format.number(item.balance_after, 8)} {item.currency}</td></tr>)}</tbody></table></div><Pager offset={ledgerOffset} limit={ledger.data.limit} itemCount={ledger.data.items.length} total={ledger.data.total} onPage={setLedgerOffset} /></>}
    </div>
    {modal && <div className={styles.modalBackdrop} onMouseDown={() => setModal(null)}>
      <div className={styles.modal} onMouseDown={(event) => event.stopPropagation()}>
        <div className={styles.modalHeader}><div><span>{t("eyebrow")}</span><h2>{modal === "allocate" ? t("allocateTitle") : t("convertTitle")}</h2></div><button onClick={() => setModal(null)} aria-label={common("cancel")}>×</button></div>
        <form className={styles.form} onSubmit={submit}>
          {modal === "allocate" ? <>
            <label>{common("currency")}<select value={currency} onChange={(event) => setCurrency(event.target.value as FiatCurrency)}><option value="TJS">TJS</option><option value="RUB">RUB</option></select></label>
            <label>{common("amount")}<input required min="0.00000001" step="0.00000001" type="number" value={amount} onChange={(event) => setAmount(event.target.value)} /></label>
          </> : <>
            <label>{t("from")}<select value={fromCurrency} onChange={(event) => { setFromCurrency(event.target.value as FiatCurrency); setPreview(null); }}><option value="TJS">TJS</option><option value="RUB">RUB</option></select></label>
            <label>{t("to")}<input readOnly value={toCurrency} /></label>
            <label>{t("sourceAmount")}<input required min="0.00000001" step="0.00000001" type="number" value={amount} onChange={(event) => { setAmount(event.target.value); setPreview(null); }} /></label>
            <div className={styles.ratePreview}>
              {previewing ? t("loadingRate") : preview ? <>
                <span>{t("currentRate")}: 1 {preview.from_currency} = {format.number(preview.effective_rate, 8)} {preview.to_currency}</span>
                {Number(preview.fee_amount) > 0 && <span>{t("referenceRate")}: {format.number(preview.reference_rate, 8)} · {t("fee")}: {format.number(preview.fee_amount, 8)} {preview.to_currency}</span>}
                <strong>{t("recipientGets")}: {format.number(preview.destination_amount, 8)} {preview.to_currency}</strong>
                <small>NBT · {format.dateTime(preview.published_at)}</small>
              </> : t("enterAmount")}
            </div>
          </>}
          <label>{common("description")}<textarea maxLength={500} value={comment} onChange={(event) => setComment(event.target.value)} /></label>
          {error && <div className={styles.formError}>{error}</div>}
          <div className={styles.formActions}><button type="button" onClick={() => setModal(null)}>{common("cancel")}</button><button disabled={saving || (modal === "convert" && !preview)}>{saving ? common("saving") : common("confirm")}</button></div>
        </form>
      </div>
    </div>}
  </>;
}
