"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { Pager } from "@/components/ui/pager";
import { useAuth } from "@/features/auth/auth-provider";
import { useAppFormat } from "@/features/i18n/use-app-format";
import { useEnumLabels } from "@/features/i18n/use-enum-labels";
import { useLocalizedError } from "@/features/i18n/use-localized-error";
import { notificationLink } from "@/features/notifications/links";
import { useNotificationMessage } from "@/features/notifications/messages";
import { notificationsApi } from "@/lib/api/notifications";
import type {
  NotificationItem,
  NotificationPreferences,
  TelegramConnection,
} from "@/lib/api/types";
import { useApiQuery } from "@/lib/hooks/use-api-query";

import styles from "./notifications-page.module.css";
import { OwnerDeliveryOperations } from "./owner-delivery-operations";

const PAGE_SIZE = 20;
const toggles: Array<{
  key: keyof NotificationPreferences;
  label: "inApp" | "telegram" | "deals" | "deposits" | "appeals" | "withdrawals";
  text: "inAppText" | "telegramText" | "dealsText" | "depositsText" | "appealsText" | "withdrawalsText";
}> = [
  { key: "in_app_enabled", label: "inApp", text: "inAppText" },
  { key: "telegram_enabled", label: "telegram", text: "telegramText" },
  { key: "deal_notifications", label: "deals", text: "dealsText" },
  { key: "deposit_notifications", label: "deposits", text: "depositsText" },
  { key: "appeal_notifications", label: "appeals", text: "appealsText" },
  { key: "withdrawal_notifications", label: "withdrawals", text: "withdrawalsText" },
];

export function NotificationsPage() {
  const t = useTranslations("notifications");
  const router = useRouter();
  const { account } = useAuth();
  const labels = useEnumLabels();
  const format = useAppFormat();
  const localizeError = useLocalizedError();
  const localizeNotification = useNotificationMessage();
  const [offset, setOffset] = useState(0);
  const list = useApiQuery(() => notificationsApi.list(PAGE_SIZE, offset), `notifications:${offset}`);
  const preferences = useApiQuery(notificationsApi.preferences, "notification-preferences");
  const telegram = useApiQuery(notificationsApi.telegramConnection, "telegram-connection");
  const [error, setError] = useState("");
  const [link, setLink] = useState<{ url: string; expires: string; bot: string } | null>(null);

  async function perform(action: () => Promise<unknown>, refresh = true) {
    setError("");
    try {
      await action();
      if (refresh) {
        await list.refetch();
        window.dispatchEvent(new Event("gigveyro:notifications-updated"));
      }
    } catch (reason) {
      setError(localizeError(reason));
    }
  }

  async function toggle(key: keyof NotificationPreferences) {
    if (!preferences.data || key === "account_id") return;
    await perform(() => notificationsApi.updatePreferences({ [key]: !preferences.data![key] }), false);
    await preferences.refetch();
  }

  async function createLink() {
    setError("");
    try {
      const result = await notificationsApi.telegramLink();
      setLink({ url: result.deep_link, expires: result.expires_at, bot: result.bot_username });
    } catch (reason) {
      setError(localizeError(reason));
    }
  }

  async function updateTelegram(
    input: Partial<Pick<TelegramConnection, "language" | "delivery_enabled">>,
  ) {
    await perform(() => notificationsApi.updateTelegram(input), false);
    await telegram.refetch();
  }

  async function disconnectTelegram() {
    if (!window.confirm(t("disconnectConfirm"))) return;
    await perform(notificationsApi.disconnectTelegram, false);
    setLink(null);
    await telegram.refetch();
  }

  async function open(item: NotificationItem) {
    if (!item.is_read) await perform(() => notificationsApi.markRead(item.id));
    const href = account ? notificationLink(item, account.role) : null;
    if (href) router.push(href);
  }

  return (
    <section>
      <div className={styles.heading}>
        <div><span>{t("eyebrow")}</span><h1>{t("title")}</h1><p>{t("subtitle")}</p></div>
        <button onClick={() => void perform(notificationsApi.markAllRead)}>{t("readAll")}</button>
      </div>
      {error && <div className={styles.error}>{error}</div>}
      <div className={styles.layout}>
        <div className={styles.feed}>
          {list.loading ? <div className={styles.state}>{t("loading")}</div>
            : list.error ? <div className={`${styles.state} ${styles.errorText}`}>{list.error}</div>
            : !list.data?.length ? <div className={styles.state}>{t("empty")}</div>
            : <>{list.data.map((item) => {
              const localized = localizeNotification(item);
              return <button key={item.id} className={item.is_read ? styles.read : ""} onClick={() => void open(item)}><i /><div><span>{labels.notification(item.type)}</span><h2>{localized.title}</h2><p>{localized.message}</p><small>{format.dateTime(item.created_at)}</small></div></button>;
            })}<Pager offset={offset} limit={PAGE_SIZE} itemCount={list.data.length} onPage={setOffset} /></>}
        </div>
        <aside className={styles.settings}>
          <h2>{t("settings")}</h2>
          {preferences.loading ? <p>{t("loading")}</p>
            : preferences.error ? <p className={styles.errorText}>{preferences.error}</p>
            : toggles.map((item) => <div className={styles.setting} key={item.key}><div><strong>{t(item.label)}</strong><span>{t(item.text)}</span></div><button aria-label={t(item.label)} className={preferences.data?.[item.key] ? styles.on : ""} onClick={() => void toggle(item.key)}><i /></button></div>)}
          <div className={styles.telegram}>
            <span>{t("telegramLink")}</span>
            {telegram.loading ? <p>{t("loading")}</p>
              : telegram.error ? <p className={styles.errorText}>{telegram.error}</p>
              : telegram.data?.connected ? <>
                <div className={styles.connection}><strong>{t("connected")}</strong><small>{telegram.data.masked_username ?? t("privateAccount")}{telegram.data.linked_at ? ` · ${format.dateTime(telegram.data.linked_at)}` : ""}</small></div>
                <div className={styles.telegramControls}>
                  <label>{t("botLanguage")}<select value={telegram.data.language} onChange={(event) => void updateTelegram({ language: event.target.value as TelegramConnection["language"] })}><option value="ru">Русский</option><option value="en">English</option><option value="tg">Тоҷикӣ</option></select></label>
                  <button className={telegram.data.delivery_enabled ? styles.on : ""} onClick={() => void updateTelegram({ delivery_enabled: !telegram.data!.delivery_enabled })}><i />{telegram.data.delivery_enabled ? t("deliveryOn") : t("deliveryOff")}</button>
                </div>
                {telegram.data.unhealthy_reason && <p className={styles.errorText}>{t("deliveryUnavailable")}</p>}
                <button className={styles.disconnect} onClick={() => void disconnectTelegram()}>{t("disconnect")}</button>
              </> : <>
                <p>{t("telegramHelp")}</p>
                <button onClick={() => void createLink()}>{t("connectTelegram")}</button>
                {link && <div className={styles.deepLink}><a href={link.url} target="_blank" rel="noopener noreferrer">{t("openBot")}</a><small>@{link.bot} · {t("validTo", { time: format.time(link.expires) })}</small></div>}
              </>}
          </div>
        </aside>
      </div>
      {account?.role === "owner" && <OwnerDeliveryOperations />}
    </section>
  );
}
