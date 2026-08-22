"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { useAppFormat } from "@/features/i18n/use-app-format";
import { useEnumLabels } from "@/features/i18n/use-enum-labels";
import { useLocalizedError } from "@/features/i18n/use-localized-error";
import { notificationsApi } from "@/lib/api/notifications";
import type { NotificationPreferences } from "@/lib/api/types";
import { useApiQuery } from "@/lib/hooks/use-api-query";

import styles from "./notifications-page.module.css";

const toggles: Array<{ key: keyof NotificationPreferences; label: "inApp" | "telegram" | "deals" | "deposits" | "appeals" | "withdrawals"; text: "inAppText" | "telegramText" | "dealsText" | "depositsText" | "appealsText" | "withdrawalsText" }> = [
  { key: "in_app_enabled", label: "inApp", text: "inAppText" },
  { key: "telegram_enabled", label: "telegram", text: "telegramText" },
  { key: "deal_notifications", label: "deals", text: "dealsText" },
  { key: "deposit_notifications", label: "deposits", text: "depositsText" },
  { key: "appeal_notifications", label: "appeals", text: "appealsText" },
  { key: "withdrawal_notifications", label: "withdrawals", text: "withdrawalsText" },
];

export function NotificationsPage() {
  const t = useTranslations("notifications");
  const labels = useEnumLabels();
  const format = useAppFormat();
  const localizeError = useLocalizedError();
  const list = useApiQuery(notificationsApi.list, "notifications");
  const preferences = useApiQuery(notificationsApi.preferences, "notification-preferences");
  const [error, setError] = useState("");
  const [code, setCode] = useState<{ value: string; expires: string; bot: string } | null>(null);

  async function perform(action: () => Promise<unknown>, refresh = true) { setError(""); try { await action(); if (refresh) { await list.refetch(); window.dispatchEvent(new Event("gigveyro:notifications-updated")); } } catch (reason) { setError(localizeError(reason)); } }
  async function toggle(key: keyof NotificationPreferences) { if (!preferences.data || key === "account_id") return; await perform(() => notificationsApi.updatePreferences({ [key]: !preferences.data![key] }), false); await preferences.refetch(); }
  async function createCode() { setError(""); try { const result = await notificationsApi.telegramCode(); setCode({ value: result.verification_code, expires: result.expires_at, bot: result.bot_username }); } catch (reason) { setError(localizeError(reason)); } }

  return <section><div className={styles.heading}><div><span>{t("eyebrow")}</span><h1>{t("title")}</h1><p>{t("subtitle")}</p></div><button onClick={() => void perform(notificationsApi.markAllRead)}>{t("readAll")}</button></div>{error && <div className={styles.error}>{error}</div>}
    <div className={styles.layout}><div className={styles.feed}>{list.loading ? <div className={styles.state}>{t("loading")}</div> : list.error ? <div className={`${styles.state} ${styles.errorText}`}>{list.error}</div> : !list.data?.length ? <div className={styles.state}>{t("empty")}</div> : list.data.map((item) => <button key={item.id} className={item.is_read ? styles.read : ""} onClick={() => !item.is_read && void perform(() => notificationsApi.markRead(item.id))}><i /><div><span>{labels.notification(item.type)}</span><h2>{item.title}</h2><p>{item.message}</p><small>{format.dateTime(item.created_at)}</small></div></button>)}</div>
      <aside className={styles.settings} style={{ minWidth: 0 }}><h2>{t("settings")}</h2>{preferences.loading ? <p>{t("loading")}</p> : preferences.error ? <p className={styles.errorText}>{preferences.error}</p> : toggles.map((item) => <div className={styles.setting} key={item.key}><div><strong>{t(item.label)}</strong><span>{t(item.text)}</span></div><button aria-label={t(item.label)} className={preferences.data?.[item.key] ? styles.on : ""} onClick={() => void toggle(item.key)}><i /></button></div>)}<div className={styles.telegram} style={{ minWidth: 0 }}><span>{t("telegramLink")}</span><p>{t("telegramHelp")}</p><button onClick={() => void createCode()}>{t("getCode")}</button>{code && <div style={{ minWidth: 0 }}><strong style={{ display: "block", maxWidth: "100%", fontSize: "clamp(16px, 2vw, 25px)", lineHeight: 1.25, letterSpacing: ".1em", overflowWrap: "anywhere", wordBreak: "break-word", userSelect: "all" }}>{code.value}</strong><small>@{code.bot} · {t("validTo", { time: format.time(code.expires) })}</small></div>}</div></aside>
    </div>
  </section>;
}
