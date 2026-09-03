"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { Pager } from "@/components/ui/pager";
import { useAppFormat } from "@/features/i18n/use-app-format";
import { useLocalizedError } from "@/features/i18n/use-localized-error";
import { notificationsApi } from "@/lib/api/notifications";
import type { NotificationDeliveryStatus } from "@/lib/api/types";
import { useApiQuery } from "@/lib/hooks/use-api-query";

import styles from "./notifications-page.module.css";

const PAGE_SIZE = 20;
const failureCategories = new Set([
  "blocked", "chat_not_found", "invalid_token", "invalid_config",
  "temporary_unavailable", "unavailable", "rate_limited",
]);

export function OwnerDeliveryOperations() {
  const t = useTranslations("notifications");
  const common = useTranslations("common");
  const format = useAppFormat();
  const localizeError = useLocalizedError();
  const [status, setStatus] = useState<NotificationDeliveryStatus | "">("FAILED");
  const [offset, setOffset] = useState(0);
  const [retrying, setRetrying] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const query = useApiQuery(
    () => notificationsApi.ownerDeliveries(status || undefined, PAGE_SIZE, offset),
    `owner-notification-deliveries:${status}:${offset}`,
  );

  async function retry(id: string) {
    setRetrying(id); setError(""); setNotice("");
    try {
      await notificationsApi.retryOwnerDelivery(id);
      setNotice(t("retryQueued"));
      await query.refetch();
    } catch (reason) {
      setError(localizeError(reason));
      await query.refetch();
    } finally { setRetrying(null); }
  }

  function failureLabel(value: string | null) {
    const category = value && failureCategories.has(value) ? value : "unknown";
    return t(`deliveryFailures.${category}`);
  }

  return <section className={styles.deliveryPanel}>
    <div className={styles.deliveryHeader}>
      <div><span>{t("deliveriesTitle")}</span><p>{t("deliveriesSubtitle")}</p></div>
      <select aria-label={common("status")} value={status} onChange={(event) => { setStatus(event.target.value as NotificationDeliveryStatus | ""); setOffset(0); }}>
        <option value="">{t("deliveryStatuses.all")}</option>
        {(["PENDING", "SENT", "FAILED"] as const).map((value) => <option value={value} key={value}>{t(`deliveryStatuses.${value}`)}</option>)}
      </select>
    </div>
    {notice && <div className={styles.deliveryNotice}>{notice}</div>}
    {error && <div className={styles.error}>{error}</div>}
    {query.loading ? <div className={styles.state}>{t("loading")}</div>
      : query.error ? <div className={`${styles.state} ${styles.errorText}`}>{query.error}</div>
      : !query.data?.length ? <div className={styles.state}>{t("deliveriesEmpty")}</div>
      : <div className={styles.deliveryTable}><table><thead><tr>
        <th>{t("deliveryChannel")}</th><th>{t("deliveryReference")}</th><th>{common("status")}</th><th>{t("deliveryAttempts")}</th><th>{t("deliveryCreated")}</th><th>{t("deliverySent")}</th><th>{t("deliveryError")}</th><th>{common("actions")}</th>
      </tr></thead><tbody>{query.data.map((item) => <tr key={item.id}>
        <td>{item.channel}</td><td><code>{shorten(item.notification_id)}</code></td><td><span data-status={item.status}>{t(`deliveryStatuses.${item.status}`)}</span></td><td>{item.attempts}</td><td>{format.dateTime(item.created_at)}</td><td>{item.sent_at ? format.dateTime(item.sent_at) : "—"}</td><td>{item.last_error ? failureLabel(item.last_error) : "—"}</td><td>{item.status === "FAILED" && <button disabled={retrying === item.id} onClick={() => void retry(item.id)}>{retrying === item.id ? t("retrying") : t("retry")}</button>}</td>
      </tr>)}</tbody></table></div>}
    {query.data && <Pager offset={offset} limit={PAGE_SIZE} itemCount={query.data.length} onPage={setOffset} />}
  </section>;
}

function shorten(value: string) {
  return value.length > 16 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value;
}
