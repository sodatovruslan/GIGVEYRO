"use client";

import { useTranslations } from "next-intl";
import { useAppFormat } from "@/features/i18n/use-app-format";
import type { MarketProviderDiagnostic } from "@/lib/api/types";
import { ownerOperationsApi } from "@/lib/api/owner-operations";
import { useApiQuery } from "@/lib/hooks/use-api-query";
import { Heading } from "../owner-components";
import baseStyles from "../operations.module.css";
import styles from "./integrations.module.css";

type Tone = "ok" | "warn" | "danger" | "neutral";
const diagnosticTone = (value: string): Tone => value === "healthy" || value === "enabled" || value === "connected" || value === "closed" ? "ok" : value === "mock" || value === "fallback" || value === "development" || value === "degraded" ? "warn" : value === "disabled" || value === "unavailable" || value === "open" ? "danger" : "neutral";

export default function IntegrationsPage() {
  const t = useTranslations("integrations");
  const common = useTranslations("common");
  const format = useAppFormat();
  const query = useApiQuery(ownerOperationsApi.integrations, "owner-integrations");
  const data = query.data;
  const diagnostic = (value: string) => ({ label: t.has(`values.${value}`) ? t(`values.${value}`) : value, technical: value, tone: diagnosticTone(value) });
  return <section><Heading title={t("title")} text={t("subtitle")} />{query.loading ? <div className={baseStyles.state}>{t("checking")}</div> : query.error ? <div className={baseStyles.error}>{query.error}</div> : data && <div className={styles.grid}>
    <Panel eyebrow={t("systemEyebrow")} title={t("system")}><Property label={common("status")} value={diagnostic(data.status)} /><Property label={t("environment")} value={diagnostic(data.environment)} /></Panel>
    <Panel eyebrow={t("providersEyebrow")} title={t("providers")}><Property label={t("deposits")} value={diagnostic(data.providers.deposit_provider)} /><Property label={t("rate")} value={diagnostic(data.providers.exchange_rate_provider)} /><Property label={t("payouts")} value={diagnostic(data.providers.payout_provider)} /></Panel>
    <MarketPanel name="Binance" provider={data.market_data.providers.binance} diagnostic={diagnostic} format={format} t={t} />
    <MarketPanel name="Bybit" provider={data.market_data.providers.bybit} diagnostic={diagnostic} format={format} t={t} />
    <Panel eyebrow={t("marketEyebrow")} title={t("aggregator")}><Property label={common("status")} value={diagnostic(data.market_data.status)} /><Property label={t("activeProvider")} value={diagnostic(data.market_data.active_provider || "unavailable")} /><Property label={t("cache")} value={diagnostic(data.market_data.cache)} /><Property label={t("referenceSymbol")} plain={data.market_data.symbol} /><Property label={t("deviation")} plain={data.market_data.deviation_bps ? `${format.number(data.market_data.deviation_bps, 2)} bps` : "—"} /></Panel>
    <Panel eyebrow={t("safetyEyebrow")} title={t("safety")}><Property label={t("trading")} value={diagnostic(data.safety.trading_enabled ? "enabled" : "disabled")} /><Property label={t("payouts")} value={diagnostic(data.safety.payout_enabled ? "enabled" : "disabled")} /><Property label={t("confirmations")} plain={String(data.safety.required_confirmations)} /><Property label={t("contract")} plain={shorten(data.safety.usdt_contract_address)} title={data.safety.usdt_contract_address} /></Panel>
  </div>}</section>;
}

function MarketPanel({ name, provider, diagnostic, format, t }: { name: string; provider: MarketProviderDiagnostic; diagnostic: (value: string) => { label: string; technical: string; tone: Tone }; format: ReturnType<typeof useAppFormat>; t: ReturnType<typeof useTranslations> }) {
  return <Panel eyebrow={t("publicMarketEyebrow")} title={`${name} ${t("marketData")}`}><Property label={t("connection")} value={diagnostic(provider.status)} /><Property label={t("access")} value={diagnostic(provider.read_only ? "readOnly" : "unavailable")} /><Property label={t("role")} value={diagnostic(provider.role)} /><Property label={t("latency")} plain={provider.latency_ms === null ? "—" : `${format.number(provider.latency_ms, 0)} ms`} /><Property label={t("lastCheck")} plain={provider.last_success_at ? format.dateTime(provider.last_success_at) : "—"} /><Property label={t("circuit")} value={diagnostic(provider.circuit)} /></Panel>;
}

function Panel({ eyebrow, title, children }: { eyebrow: string; title: string; children: React.ReactNode }) { return <article className={styles.panel}><span>{eyebrow}</span><h2>{title}</h2>{children}</article>; }
function Property({ label, value, plain, title }: { label: string; value?: { label: string; technical: string; tone: Tone }; plain?: string; title?: string }) { return <div className={styles.property}><span>{label}</span>{value ? <span className={`${styles.badge} ${styles[value.tone]}`} title={value.technical}>{value.label}<small>{value.technical}</small></span> : <strong title={title}>{plain || "—"}</strong>}</div>; }
function shorten(value: string) { return value?.length > 18 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value || "—"; }
