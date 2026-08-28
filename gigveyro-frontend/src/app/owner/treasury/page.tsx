"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { useAppFormat } from "@/features/i18n/use-app-format";
import { useLocalizedError } from "@/features/i18n/use-localized-error";
import { ownerOperationsApi } from "@/lib/api/owner-operations";
import type { RiskPolicyInput, RiskPreview } from "@/lib/api/types";
import { useApiQuery } from "@/lib/hooks/use-api-query";
import { Heading } from "../owner-components";
import styles from "./treasury.module.css";

const defaults: RiskPolicyInput = {
  reserve_coverage_enabled: false, minimum_reserve_ratio_bps: 10000,
  warning_reserve_ratio_bps: 11000, max_treasury_data_age_seconds: 300,
  single_deal_enabled: false, max_single_deal_usdt: null,
  user_exposure_enabled: false, max_user_exposure_usdt: null,
  pending_withdrawals_enabled: false, max_pending_withdrawals_usdt: null,
  total_open_deals_enabled: false, max_total_open_deals_usdt: null,
  minimum_external_reserve_enabled: false, minimum_external_usdt_reserve: null,
};

export default function TreasuryPage() {
  const t = useTranslations("treasury");
  const common = useTranslations("common");
  const format = useAppFormat();
  const localizeError = useLocalizedError();
  const summary = useApiQuery(ownerOperationsApi.treasurySummary, "treasury-summary");
  const policy = useApiQuery(ownerOperationsApi.riskPolicy, "risk-policy");
  const [form, setForm] = useState<RiskPolicyInput>(defaults);
  const [preview, setPreview] = useState<RiskPreview | null>(null);
  const [draftId, setDraftId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!policy.data) return;
    const timeout = window.setTimeout(() => setForm({ ...defaults, ...policy.data }), 0);
    return () => window.clearTimeout(timeout);
  }, [policy.data]);
  const set = <K extends keyof RiskPolicyInput>(key: K, value: RiskPolicyInput[K]) => {
    setForm((current) => ({ ...current, [key]: value })); setPreview(null); setDraftId(null);
  };
  async function refresh() { setBusy(true); setError(""); try { await ownerOperationsApi.refreshTreasury(); await summary.refetch(); } catch (e) { setError(localizeError(e)); } finally { setBusy(false); } }
  async function runPreview() { setBusy(true); setError(""); try { setPreview(await ownerOperationsApi.previewRiskPolicy(form)); } catch (e) { setError(localizeError(e)); } finally { setBusy(false); } }
  async function createDraft() { setBusy(true); setError(""); try { const draft = await ownerOperationsApi.createRiskPolicy(form); setDraftId(draft.id); } catch (e) { setError(localizeError(e)); } finally { setBusy(false); } }
  async function activate() { if (!draftId || !preview) return; setBusy(true); try { await ownerOperationsApi.activateRiskPolicy(draftId); setDraftId(null); setPreview(null); await Promise.all([policy.refetch(), summary.refetch()]); } catch (e) { setError(localizeError(e)); } finally { setBusy(false); } }
  const s = summary.data;
  return <section>
    <Heading title={t("title")} text={t("subtitle")} />
    {error && <div className={styles.error}>{error}</div>}
    <div className={styles.toolbar}><span>{s?.external_observed_at ? `${t("observed")}: ${format.dateTime(s.external_observed_at)}` : t("notObserved")}</span><button onClick={refresh} disabled={busy}>{busy ? common("loading") : t("refresh")}</button></div>
    <div className={styles.status} data-status={s?.risk_status || "unknown"}><strong>{t(`statuses.${s?.risk_status || "unknown"}`)}</strong><span>{t("policyVersion", { version: s?.policy_version || 1 })}</span></div>
    <div className={styles.grid}>
      <Card title={t("externalUsdt")} value={s ? `${format.number(s.external_bybit_usdt, 8)} USDT` : "—"} hint={t("liquidReserve")} />
      <Card title={t("externalUsdc")} value={s ? `${format.number(s.external_bybit_usdc, 8)} USDC` : "—"} hint={t("usdcExcluded")} />
      <Card title={t("totalLiability")} value={s ? `${format.number(s.total_internal_liability_usdt, 8)} USDT` : "—"} hint={t("liabilityHint")} />
      <Card title={t("coverage")} value={s?.coverage_ratio_bps == null ? "—" : `${s.coverage_ratio_bps} bps`} hint={t("coverageHint")} />
      <Card title={t("surplus")} value={s ? `${format.number(s.reserve_surplus_usdt, 8)} USDT` : "—"} hint={t("reserveOnly")} />
      <Card title={t("deficit")} value={s ? `${format.number(s.reserve_deficit_usdt, 8)} USDT` : "—"} hint={t("reserveOnly")} />
    </div>
    <div className={styles.breakdown}><Card title={t("userLiability")} value={s ? format.number(s.internal_user_liability_usdt, 8) : "—"} hint={`USDT · ${t("frozen")}: ${s ? format.number(s.frozen_usdt, 8) : "—"}`} /><Card title={t("merchantLiability")} value={s ? format.number(s.merchant_liability_usdt, 8) : "—"} hint={`USDT · ${t("pending")}: ${s ? format.number(s.pending_withdrawal_usdt, 8) : "—"}`} /><Card title={t("ownerProfit")} value={s ? format.number(s.owner_profit_usdt, 8) : "—"} hint={t("profitSeparate")} /></div>
    <article className={styles.editor}><h2>{t("riskPolicy")}</h2><p>{t("defaultOff")}</p>
      <Toggle label={t("reserveEnforcement")} checked={form.reserve_coverage_enabled} onChange={(v) => set("reserve_coverage_enabled", v)} />
      <div className={styles.fields}><NumberField label={t("minimumRatio")} value={form.minimum_reserve_ratio_bps} onChange={(v) => set("minimum_reserve_ratio_bps", v)} /><NumberField label={t("warningRatio")} value={form.warning_reserve_ratio_bps} onChange={(v) => set("warning_reserve_ratio_bps", v)} /><NumberField label={t("freshness")} value={form.max_treasury_data_age_seconds} onChange={(v) => set("max_treasury_data_age_seconds", v)} /></div>
      {[ ["single_deal_enabled", "max_single_deal_usdt", "singleDeal"], ["user_exposure_enabled", "max_user_exposure_usdt", "userExposure"], ["pending_withdrawals_enabled", "max_pending_withdrawals_usdt", "pendingLimit"], ["total_open_deals_enabled", "max_total_open_deals_usdt", "openDeals"] ].map(([enabled, limit, label]) => <div className={styles.rule} key={enabled}><Toggle label={t(label)} checked={Boolean(form[enabled as keyof RiskPolicyInput])} onChange={(v) => set(enabled as keyof RiskPolicyInput, v as never)} /><input type="number" min="0" step="0.00000001" value={(form[limit as keyof RiskPolicyInput] as string | null) || ""} onChange={(e) => set(limit as keyof RiskPolicyInput, (e.target.value || null) as never)} placeholder="USDT" /></div>)}
      <div className={styles.actions}><button onClick={runPreview} disabled={busy}>{t("preview")}</button><button onClick={createDraft} disabled={busy || !preview}>{t("createDraft")}</button><button onClick={activate} disabled={busy || !draftId || !preview}>{t("activate")}</button></div>
      {preview && <div className={styles.preview}><strong>{t(`decisions.${preview.reserve_decision}`)}</strong><span>{preview.reason_code ? t(`reasons.${preview.reason_code}`) : t("noBlockReason")}</span></div>}
    </article>
  </section>;
}

function Card({ title, value, hint }: { title: string; value: string; hint: string }) { return <article className={styles.card}><span>{title}</span><strong>{value}</strong><small>{hint}</small></article>; }
function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) { return <label className={styles.toggle}><input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} /><span>{label}</span></label>; }
function NumberField({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) { return <label><span>{label}</span><input type="number" min="0" value={value} onChange={(e) => onChange(Number(e.target.value))} /></label>; }
