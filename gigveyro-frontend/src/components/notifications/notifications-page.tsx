"use client";

import { useState } from "react";

import { ApiError } from "@/lib/api/error";
import { notificationsApi } from "@/lib/api/notifications";
import type { NotificationPreferences } from "@/lib/api/types";
import { useApiQuery } from "@/lib/hooks/use-api-query";

import styles from "./notifications-page.module.css";

const toggles: Array<{ key: keyof NotificationPreferences; label: string; text: string }> = [
  { key: "in_app_enabled", label: "В приложении", text: "Показывать уведомления в кабинете" },
  { key: "telegram_enabled", label: "Telegram", text: "Отправлять сообщения в Telegram" },
  { key: "deal_notifications", label: "Сделки", text: "Изменения статусов сделок" },
  { key: "deposit_notifications", label: "Депозиты", text: "Зачисления и подтверждения" },
  { key: "appeal_notifications", label: "Апелляции", text: "Новые действия по спорам" },
  { key: "withdrawal_notifications", label: "Выводы", text: "Статусы заявок на вывод" },
];

export function NotificationsPage() {
  const list = useApiQuery(notificationsApi.list, "notifications");
  const preferences = useApiQuery(notificationsApi.preferences, "notification-preferences");
  const [error, setError] = useState("");
  const [code, setCode] = useState<{ value: string; expires: string; bot: string } | null>(null);

  async function perform(action: () => Promise<unknown>, refresh = true) { setError(""); try { await action(); if (refresh) await list.refetch(); } catch (reason) { setError(reason instanceof ApiError ? reason.message : "Не удалось выполнить действие."); } }
  async function toggle(key: keyof NotificationPreferences) { if (!preferences.data || key === "account_id") return; await perform(() => notificationsApi.updatePreferences({ [key]: !preferences.data![key] }), false); await preferences.refetch(); }
  async function createCode() { setError(""); try { const result = await notificationsApi.telegramCode(); setCode({ value: result.verification_code, expires: result.expires_at, bot: result.bot_username }); } catch (reason) { setError(reason instanceof ApiError ? reason.message : "Не удалось получить код."); } }

  return <section><div className={styles.heading}><div><span>COMMUNICATION CENTER</span><h1>Уведомления</h1><p>События платформы и каналы доставки</p></div><button onClick={() => void perform(notificationsApi.markAllRead)}>Прочитать все</button></div>{error&&<div className={styles.error}>{error}</div>}
    <div className={styles.layout}><div className={styles.feed}>{list.loading?<div className={styles.state}>Загрузка…</div>:list.error?<div className={`${styles.state} ${styles.errorText}`}>{list.error}</div>:!list.data?.length?<div className={styles.state}>Новых уведомлений нет</div>:list.data.map((item)=><button key={item.id} className={item.is_read?styles.read:""} onClick={()=>!item.is_read&&void perform(()=>notificationsApi.markRead(item.id))}><i/><div><span>{item.type.replaceAll("_"," ")}</span><h2>{item.title}</h2><p>{item.message}</p><small>{new Intl.DateTimeFormat("ru-RU",{dateStyle:"medium",timeStyle:"short"}).format(new Date(item.created_at))}</small></div></button>)}</div>
      <aside className={styles.settings}><h2>Настройки</h2>{preferences.loading?<p>Загрузка…</p>:preferences.error?<p className={styles.errorText}>{preferences.error}</p>:toggles.map((item)=><div className={styles.setting} key={item.key}><div><strong>{item.label}</strong><span>{item.text}</span></div><button className={preferences.data?.[item.key]?styles.on:""} onClick={()=>void toggle(item.key)}><i/></button></div>)}<div className={styles.telegram}><span>TELEGRAM LINK</span><p>Получите одноразовый код и отправьте его боту.</p><button onClick={()=>void createCode()}>Получить код</button>{code&&<div><strong>{code.value}</strong><small>@{code.bot} · до {new Intl.DateTimeFormat("ru-RU",{timeStyle:"short"}).format(new Date(code.expires))}</small></div>}</div></aside>
    </div>
  </section>;
}
