"use client";

import { type FormEvent, useState } from "react";

import { ApiError } from "@/lib/api/error";
import { depositsApi } from "@/lib/api/deposits";
import type { Deposit, DepositStatus } from "@/lib/api/types";
import { useApiQuery } from "@/lib/hooks/use-api-query";

import styles from "./deposits-page.module.css";

export function DepositsPage({ owner }: { owner: boolean }) {
  const [status, setStatus] = useState<DepositStatus | "">("");
  const query = useApiQuery(() => depositsApi.list(owner, status || undefined), `deposits:${owner}:${status}`);
  const [modal, setModal] = useState(false); const [amount, setAmount] = useState(""); const [created, setCreated] = useState<Deposit | null>(null); const [error, setError] = useState(""); const [saving, setSaving] = useState(false);
  async function create(event: FormEvent) { event.preventDefault(); setSaving(true); setError(""); try { const result = await depositsApi.create(amount); setCreated(result); setAmount(""); await query.refetch(); } catch (reason) { setError(reason instanceof ApiError ? reason.message : "Не удалось создать депозит."); } finally { setSaving(false); } }
  function close() { setModal(false); setCreated(null); setError(""); }
  return <section><div className={styles.heading}><div><span>{owner ? "OWNER MONITORING" : "USDT FUNDING"}</span><h1>Депозиты</h1><p>{owner ? "Мониторинг входящих пополнений пользователей" : "Создание и отслеживание пополнений USDT TRC20"}</p></div>{!owner && <button onClick={() => setModal(true)}>＋ Пополнить</button>}</div>
    <select className={styles.filter} aria-label="Статус" value={status} onChange={(e) => setStatus(e.target.value as typeof status)}><option value="">Все статусы</option>{["waiting","detected","confirming","confirmed","credited","expired","failed","amount_mismatch"].map((value) => <option key={value} value={value}>{statusLabel(value as DepositStatus)}</option>)}</select>
    {error && <div className={styles.error}>{error}</div>}{query.error && <div className={styles.error}>{query.error}</div>}
    <div className={styles.card}>{query.loading ? <div className={styles.state}>Загружаем депозиты…</div> : !query.data?.items.length ? <div className={styles.state}>Депозитов пока нет</div> : <div className={styles.table}><table><thead><tr><th>ID / дата</th>{owner && <th>Аккаунт</th>}<th>Ожидается</th><th>Получено / зачислено</th><th>Подтверждения</th><th>Статус</th><th>Транзакция</th></tr></thead><tbody>{query.data.items.map((item) => <tr key={item.id}><td><strong>{item.public_id}</strong><small>{formatDate(item.created_at)}</small></td>{owner && <td><code>{item.account_id}</code></td>}<td>{item.expected_amount} {item.asset}<small>{item.network}</small></td><td>{item.received_amount || "—"}<small>зачислено: {item.credited_amount || "—"}</small></td><td>{item.confirmations} / {item.required_confirmations}</td><td><span className={`${styles.status} ${styles[item.status]}`}>{statusLabel(item.status)}</span></td><td><code>{item.tx_hash ? shorten(item.tx_hash) : "—"}</code></td></tr>)}</tbody></table></div>}</div>
    {modal && <div className={styles.modalBackdrop} onMouseDown={close}><div className={styles.modal} onMouseDown={(e) => e.stopPropagation()}><h2>{created ? "Депозит создан" : "Пополнение USDT"}</h2><p>{created ? "Отправьте точную сумму на адрес до истечения срока." : "Backend создаст уникальный депозитный intent и адрес."}</p>{created ? <div className={styles.intent}><span>Сумма</span><strong>{created.expected_amount} {created.asset}</strong><span>Сеть</span><b>{created.network}</b><span>Адрес</span><code>{created.deposit_address}</code><span>Действителен до</span><b>{formatDate(created.expires_at)}</b></div> : <form onSubmit={create}><label>Сумма USDT<input required type="number" min="0.00000001" step="0.00000001" value={amount} onChange={(e) => setAmount(e.target.value)} /></label>{error && <div className={styles.error}>{error}</div>}<div className={styles.actions}><button type="button" onClick={close}>Отмена</button><button disabled={saving}>{saving ? "Создаём…" : "Создать депозит"}</button></div></form>}{created && <div className={styles.actions}><button onClick={close}>Готово</button></div>}</div></div>}
  </section>;
}
function statusLabel(status: DepositStatus) { return ({ waiting:"Ожидает",detected:"Обнаружен",confirming:"Подтверждается",confirmed:"Подтверждён",credited:"Зачислен",expired:"Истёк",failed:"Ошибка",amount_mismatch:"Сумма не совпала" } as const)[status]; }
function formatDate(value: string) { return new Intl.DateTimeFormat("ru-RU", { dateStyle: "short", timeStyle: "short" }).format(new Date(value)); }
function shorten(value: string) { return value.length > 18 ? `${value.slice(0, 8)}…${value.slice(-7)}` : value; }
