"use client";

import { useState } from "react";

import { ApiError } from "@/lib/api/error";
import { ownerOperationsApi } from "@/lib/api/owner-operations";
import type { MerchantWithdrawal } from "@/lib/api/types";
import { useApiQuery } from "@/lib/hooks/use-api-query";

import { Heading } from "../owner-components";
import styles from "../operations.module.css";

type Action = "approve" | "reject" | "mark-paid";
export default function OwnerWithdrawalsPage() {
  const [status, setStatus] = useState<MerchantWithdrawal["status"] | "">("");
  const query = useApiQuery(() => ownerOperationsApi.withdrawals(status || undefined), `owner-withdrawals:${status}`);
  const [target, setTarget] = useState<{ item: MerchantWithdrawal; action: Action } | null>(null);
  const [comment, setComment] = useState(""); const [error, setError] = useState(""); const [saving, setSaving] = useState(false);
  async function act() { if (!target) return; setSaving(true); setError(""); try { const value = comment || null; if (target.action === "approve") await ownerOperationsApi.approveWithdrawal(target.item.id, value); else if (target.action === "reject") await ownerOperationsApi.rejectWithdrawal(target.item.id, value); else await ownerOperationsApi.markWithdrawalPaid(target.item.id, value); setTarget(null); setComment(""); await query.refetch(); } catch (reason) { setError(reason instanceof ApiError ? reason.message : "Не удалось изменить заявку."); } finally { setSaving(false); } }
  return <section><Heading title="Выводы" text="Проверка, подтверждение и фиксация выплат мерчантам" />
    <div className={styles.toolbar}><select aria-label="Статус" value={status} onChange={(e) => setStatus(e.target.value as typeof status)}><option value="">Все статусы</option><option value="pending">Ожидает</option><option value="approved">Одобрена</option><option value="paid">Выплачена</option><option value="rejected">Отклонена</option><option value="cancelled">Отменена</option></select></div>
    {error && <div className={styles.error}>{error}</div>}{query.error && <div className={styles.error}>{query.error}</div>}
    <div className={styles.card}>{query.loading ? <div className={styles.state}>Загружаем выводы…</div> : !query.data?.items.length ? <div className={styles.state}>Заявок не найдено</div> : <div className={styles.table}><table><thead><tr><th>ID / дата</th><th>Мерчант</th><th>Назначение</th><th>Сумма</th><th>Статус</th><th>Действия</th></tr></thead><tbody>{query.data.items.map((item) => <tr key={item.id}><td><strong>{item.public_id}</strong><small>{formatDate(item.created_at)}</small></td><td><code>{item.merchant_id}</code></td><td>{item.destination_type === "bybit_uid" ? "Bybit UID" : "USDT TRC20"}<small>{item.destination}</small></td><td><strong>{item.amount} {item.currency.toUpperCase()}</strong></td><td><span className={`${styles.status} ${styles[item.status]}`}>{statusLabel(item.status)}</span></td><td><div className={styles.actions}>{item.status === "pending" && <><button onClick={() => setTarget({ item, action: "approve" })}>Одобрить</button><button onClick={() => setTarget({ item, action: "reject" })}>Отклонить</button></>}{item.status === "approved" && <button onClick={() => setTarget({ item, action: "mark-paid" })}>Отметить выплату</button>}</div></td></tr>)}</tbody></table></div>}</div>
    {target && <div className={styles.modalBackdrop} onMouseDown={() => setTarget(null)}><div className={styles.modal} onMouseDown={(e) => e.stopPropagation()}><h2>{actionLabel(target.action)}</h2><p>Заявка {target.item.public_id} · {target.item.amount} {target.item.currency.toUpperCase()}</p><label>Комментарий OWNER<textarea maxLength={500} value={comment} onChange={(e) => setComment(e.target.value)} /></label>{error && <div className={styles.error}>{error}</div>}<footer><button onClick={() => setTarget(null)}>Отмена</button><button disabled={saving} onClick={() => void act()}>{saving ? "Сохраняем…" : "Подтвердить"}</button></footer></div></div>}
  </section>;
}
function statusLabel(status: MerchantWithdrawal["status"]) { return ({ pending: "Ожидает", approved: "Одобрена", paid: "Выплачена", rejected: "Отклонена", cancelled: "Отменена" } as const)[status]; }
function actionLabel(action: Action) { return ({ approve: "Одобрить вывод", reject: "Отклонить вывод", "mark-paid": "Подтвердить выплату" } as const)[action]; }
function formatDate(value: string) { return new Intl.DateTimeFormat("ru-RU", { dateStyle: "short", timeStyle: "short" }).format(new Date(value)); }
