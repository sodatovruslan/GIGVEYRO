"use client";

import { type FormEvent, useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { useAppFormat } from "@/features/i18n/use-app-format";
import { useLocalizedError } from "@/features/i18n/use-localized-error";
import { ownerOperationsApi } from "@/lib/api/owner-operations";
import type { FeeComponent, FeePolicy, FeePreview, FeeType } from "@/lib/api/types";
import { useApiQuery } from "@/lib/hooks/use-api-query";
import { Pager } from "@/components/ui/pager";
import { Heading } from "../owner-components";
import styles from "./fees.module.css";

const feeTypes: FeeType[] = ["deal_fee", "fiat_conversion_spread", "withdrawal_fee", "merchant_fee"];
type FormComponent = { enabled: boolean; percent: string; fixed: string; minimum: string; maximum: string; payer: "USER" | "MERCHANT" | "" };
type FormState = Record<FeeType, FormComponent>;

const emptyForm = (): FormState => Object.fromEntries(feeTypes.map((type) => [type, { enabled: false, percent: "0", fixed: "0", minimum: "", maximum: "", payer: type === "fiat_conversion_spread" ? "USER" : "" }])) as FormState;

export default function OwnerFeesPage() {
  const t = useTranslations("fees");
  const common = useTranslations("common");
  const format = useAppFormat();
  const localizeError = useLocalizedError();
  const policy = useApiQuery(ownerOperationsApi.feePolicy, "owner-fee-policy");
  const summary = useApiQuery(ownerOperationsApi.profitSummary, "owner-profit-summary");
  const [offset, setOffset] = useState(0);
  const [feeFilter, setFeeFilter] = useState<FeeType | "">("");
  const [currencyFilter, setCurrencyFilter] = useState("");
  const entries = useApiQuery(() => ownerOperationsApi.profitEntries({ feeType: feeFilter || undefined, currency: currencyFilter || undefined, offset }), `owner-profit:${feeFilter}:${currencyFilter}:${offset}`);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [draft, setDraft] = useState<FeePolicy | null>(null);
  const [previewAmount, setPreviewAmount] = useState("1000");
  const [preview, setPreview] = useState<FeePreview | null>(null);
  const [period, setPeriod] = useState<"today" | "7d" | "30d" | "all">("30d");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    if (!policy.data) return;
    const next = emptyForm();
    policy.data.components.forEach((component) => {
      next[component.fee_type] = {
        enabled: component.enabled,
        percent: String(component.percent_bps),
        fixed: component.fixed_fee,
        minimum: component.min_fee || "",
        maximum: component.max_fee || "",
        payer: component.payer || "",
      };
    });
    const timeout = window.setTimeout(() => setForm(next), 0);
    return () => window.clearTimeout(timeout);
  }, [policy.data]);

  function update(type: FeeType, patch: Partial<FormComponent>) {
    setDraft(null); setPreview(null);
    setForm((current) => ({ ...current, [type]: { ...current[type], ...patch } }));
  }

  async function createDraft(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(""); setNotice("");
    try {
      const components = Object.fromEntries(feeTypes.map((type) => [type, {
        enabled: form[type].enabled,
        percent_bps: Number(form[type].percent),
        fixed_fee: form[type].fixed || "0",
        min_fee: form[type].minimum || null,
        max_fee: form[type].maximum || null,
        payer: form[type].payer || null,
      }])) as Parameters<typeof ownerOperationsApi.createFeePolicy>[0];
      const created = await ownerOperationsApi.createFeePolicy(components);
      setDraft(created); setNotice(t("draftCreated", { version: created.version }));
    } catch (reason) { setError(localizeError(reason)); } finally { setBusy(false); }
  }

  async function runPreview() {
    if (!draft) return; setBusy(true); setError("");
    try { setPreview(await ownerOperationsApi.previewFee("fiat_conversion_spread", "TJS", previewAmount, draft.id)); }
    catch (reason) { setError(localizeError(reason)); } finally { setBusy(false); }
  }

  async function activate() {
    if (!draft || !preview) return; setBusy(true); setError("");
    try {
      await ownerOperationsApi.activateFeePolicy(draft.id);
      setNotice(t("activated", { version: draft.version })); setDraft(null); setPreview(null);
      await Promise.all([policy.refetch(), summary.refetch(), entries.refetch()]);
    } catch (reason) { setError(localizeError(reason)); } finally { setBusy(false); }
  }

  const metrics = summary.data?.periods[period] || [];
  return <section>
    <Heading title={t("title")} text={t("subtitle")} />
    {error && <div className={styles.error}>{error}</div>}{notice && <div className={styles.notice}>{notice}</div>}
    <div className={styles.topGrid}>
      <article className={styles.panel}><span>{t("activePolicy")}</span><h2>{policy.data ? `v${policy.data.version}` : "—"}</h2><p>{policy.data?.effective_from ? format.dateTime(policy.data.effective_from) : common("loading")}</p><strong className={styles.safe}>{t("defaultSafety")}</strong></article>
      <article className={styles.panel}><span>{t("accountingBoundary")}</span><h2>{t("profitNotTreasury")}</h2><p>{t("treasuryHint")}</p></article>
    </div>
    <form onSubmit={createDraft}>
      <div className={styles.sectionHeader}><div><span>{t("configuration")}</span><h2>{t("feeComponents")}</h2></div></div>
      <div className={styles.componentGrid}>{feeTypes.map((type) => <ComponentCard key={type} type={type} value={form[type]} current={policy.data?.components.find((item) => item.fee_type === type)} update={update} t={t} />)}</div>
      <div className={styles.actions}><button disabled={busy || policy.loading}>{busy ? common("saving") : t("createDraft")}</button></div>
    </form>
    {draft && <article className={styles.previewPanel}><div><span>{t("preview")}</span><h2>{t("draftVersion", { version: draft.version })}</h2></div><label>{t("exampleAmount")}<input type="number" min="0.00000001" step="0.00000001" value={previewAmount} onChange={(event) => { setPreviewAmount(event.target.value); setPreview(null); }} /></label><button type="button" onClick={runPreview} disabled={busy}>{t("calculatePreview")}</button>{preview && <div className={styles.previewValues}><Metric label={t("gross")} value={`${format.number(preview.gross, 8)} ${preview.currency}`} /><Metric label={t("fee")} value={`${format.number(preview.total_fee, 8)} ${preview.currency}`} /><Metric label={t("net")} value={`${format.number(preview.net, 8)} ${preview.currency}`} /></div>}<button className={styles.activate} type="button" onClick={activate} disabled={busy || !preview}>{t("activate")}</button></article>}
    <div className={styles.sectionHeader}><div><span>{t("profitOverview")}</span><h2>{t("businessProfit")}</h2></div><select value={period} onChange={(event) => setPeriod(event.target.value as typeof period)}><option value="today">{t("today")}</option><option value="7d">{t("sevenDays")}</option><option value="30d">{t("thirtyDays")}</option><option value="all">{t("allTime")}</option></select></div>
    <div className={styles.metrics}>{!metrics.length ? <div className={styles.empty}>{t("noProfit")}</div> : metrics.map((item) => <article key={`${item.currency}:${item.fee_type}`} className={styles.metricCard}><span>{t(`types.${item.fee_type}`)} · {item.currency}</span><strong>{format.number(item.total_fees, 8)}</strong><small>{t("volume")}: {format.number(item.gross_volume, 8)} · {t("operationsCount", { count: item.transaction_count })}</small><small>{t("average")}: {format.number(item.average_fee, 8)}</small></article>)}</div>
    <div className={styles.sectionHeader}><div><span>{t("immutableLedger")}</span><h2>{t("profitHistory")}</h2></div><div className={styles.filters}><select value={feeFilter} onChange={(event) => { setFeeFilter(event.target.value as FeeType | ""); setOffset(0); }}><option value="">{t("allTypes")}</option>{feeTypes.map((type) => <option key={type} value={type}>{t(`types.${type}`)}</option>)}</select><select value={currencyFilter} onChange={(event) => { setCurrencyFilter(event.target.value); setOffset(0); }}><option value="">{t("allCurrencies")}</option><option>TJS</option><option>RUB</option><option>USDT</option></select></div></div>
    <div className={styles.tableWrap}>{entries.loading ? <div className={styles.empty}>{common("loading")}</div> : !entries.data?.items.length ? <div className={styles.empty}>{t("noProfit")}</div> : <><table><thead><tr><th>{common("date")}</th><th>{common("type")}</th><th>{common("currency")}</th><th>{t("gross")}</th><th>{t("fee")}</th><th>{t("policy")}</th></tr></thead><tbody>{entries.data.items.map((item) => <tr key={item.id}><td>{format.dateTime(item.created_at)}</td><td>{t(`types.${item.fee_type}`)}</td><td>{item.currency}</td><td>{format.number(item.gross_amount, 8)}</td><td className={styles.positive}>{format.number(item.fee_amount, 8)}</td><td>v{item.policy_version}</td></tr>)}</tbody></table><Pager offset={offset} limit={entries.data.limit} itemCount={entries.data.items.length} total={entries.data.total} onPage={setOffset} /></>}</div>
  </section>;
}

function ComponentCard({ type, value, current, update, t }: { type: FeeType; value: FormComponent; current?: FeeComponent; update: (type: FeeType, patch: Partial<FormComponent>) => void; t: ReturnType<typeof useTranslations> }) {
  const supported = type === "fiat_conversion_spread";
  return <article className={styles.component}><div className={styles.componentTitle}><div><span>{supported ? t("enforced") : t("architectureOnly")}</span><h3>{t(`types.${type}`)}</h3></div><label className={styles.toggle}><input type="checkbox" checked={value.enabled} disabled={!supported} onChange={(event) => update(type, { enabled: event.target.checked })} /><i /></label></div><p>{supported ? t("conversionSemantics") : t("unsupportedHint")}</p><div className={styles.fields}><label>{type === "fiat_conversion_spread" ? t("spreadBps") : t("percentBps")}<input type="number" min="0" max="5000" value={value.percent} disabled={!supported} onChange={(event) => update(type, { percent: event.target.value })} /></label><label>{t("fixedFee")}<input value={value.fixed} disabled={!supported} onChange={(event) => update(type, { fixed: event.target.value })} /></label><label>{t("minFee")}<input value={value.minimum} disabled={!supported} onChange={(event) => update(type, { minimum: event.target.value })} /></label><label>{t("maxFee")}<input value={value.maximum} disabled={!supported} onChange={(event) => update(type, { maximum: event.target.value })} /></label><label>{t("payer")}<select value={value.payer} disabled><option value="">—</option><option value="USER">USER</option></select></label></div><small>{t("currentState")}: {current?.enabled ? t("enabled") : t("disabled")}</small></article>;
}

function Metric({ label, value }: { label: string; value: string }) { return <div><span>{label}</span><strong>{value}</strong></div>; }
