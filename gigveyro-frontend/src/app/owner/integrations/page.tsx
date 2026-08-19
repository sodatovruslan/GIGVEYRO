"use client";

import { ownerOperationsApi } from "@/lib/api/owner-operations";
import { useApiQuery } from "@/lib/hooks/use-api-query";

import { Heading } from "../owner-components";
import styles from "../operations.module.css";

export default function IntegrationsPage() {
  const query = useApiQuery(ownerOperationsApi.integrations, "owner-integrations");
  const data = query.data;
  return <section><Heading title="Интеграции" text="Безопасная диагностика подключённых backend-провайдеров" />
    {query.loading ? <div className={styles.state}>Проверяем интеграции…</div> : query.error ? <div className={styles.error}>{query.error}</div> : data && <div className={styles.grid}>
      <Panel eyebrow="SYSTEM" title="Состояние"><Property label="Статус" value={data.status} good={data.status === "healthy"} /><Property label="Окружение" value={data.environment} /></Panel>
      <Panel eyebrow="PROVIDERS" title="Провайдеры"><Property label="Депозиты" value={data.providers.deposit_provider} /><Property label="Курс" value={data.providers.exchange_rate_provider} /><Property label="Выплаты" value={data.providers.payout_provider} /></Panel>
      <Panel eyebrow="SAFETY" title="Контур выплат"><Property label="Выплаты" value={data.safety.payout_enabled ? "Включены" : "Отключены"} good={data.safety.payout_enabled} /><Property label="Подтверждения" value={String(data.safety.required_confirmations)} /><Property label="Контракт USDT" value={shorten(data.safety.usdt_contract_address)} /></Panel>
    </div>}
  </section>;
}

function Panel({ eyebrow, title, children }: { eyebrow: string; title: string; children: React.ReactNode }) { return <article className={styles.panel}><span>{eyebrow}</span><h2>{title}</h2>{children}</article>; }
function Property({ label, value, good }: { label: string; value: string; good?: boolean }) { return <div className={styles.property}><span>{label}</span><strong className={good === undefined ? "" : good ? styles.ok : styles.warn}>{value || "—"}</strong></div>; }
function shorten(value: string) { return value?.length > 18 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value || "—"; }
