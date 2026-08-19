"use client";

import { type FormEvent, useState } from "react";

import { PageHeading } from "@/app/user/user-components";
import { ApiError } from "@/lib/api/error";
import { merchantApi } from "@/lib/api/merchant";
import type { MerchantWithdrawal } from "@/lib/api/types";
import { useApiQuery } from "@/lib/hooks/use-api-query";

import styles from "../../user/user.module.css";

export default function MerchantWithdrawalsPage() {
  const query = useApiQuery(merchantApi.withdrawals, "merchant-withdrawals");
  const [modal, setModal] = useState(false);
  const [amount, setAmount] = useState("");
  const [destinationType, setDestinationType] = useState<MerchantWithdrawal["destination_type"]>("usdt_trc20_address");
  const [destination, setDestination] = useState("");
  const [comment, setComment] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function create(event: FormEvent) {
    event.preventDefault(); setSaving(true); setError("");
    try { await merchantApi.createWithdrawal({ amount, destination_type: destinationType, destination, comment: comment || null }); setModal(false); setAmount(""); setDestination(""); setComment(""); await query.refetch(); }
    catch (reason) { setError(reason instanceof ApiError ? reason.message : "Не удалось создать заявку."); }
    finally { setSaving(false); }
  }

  async function cancel(id: string) {
    setError(""); try { await merchantApi.cancelWithdrawal(id); await query.refetch(); }
    catch (reason) { setError(reason instanceof ApiError ? reason.message : "Не удалось отменить заявку."); }
  }

  return <section><div className={styles.contentHeader} style={{ padding: 0, border: 0, marginBottom: 27 }}><PageHeading eyebrow="PAYOUTS" title="Вывод средств" text="Заявки на вывод USDT" /><button onClick={() => setModal(true)}>＋ Создать заявку</button></div>
    {error && <div className={styles.inlineError}>{error}</div>}
    <div className={styles.contentCard}>{query.loading ? <div className={styles.state}>Загружаем заявки…</div> : query.error ? <div className={`${styles.state} ${styles.errorText}`}>{query.error}</div> : !query.data?.items.length ? <div className={styles.state}>Заявок пока нет</div> : <div className={styles.tableScroll}><table><thead><tr><th>ID</th><th>Дата</th><th>Назначение</th><th>Сумма</th><th>Статус</th><th /></tr></thead><tbody>{query.data.items.map((item) => <tr key={item.id}><td>{item.public_id}</td><td>{new Intl.DateTimeFormat("ru-RU", { dateStyle: "short", timeStyle: "short" }).format(new Date(item.created_at))}</td><td>{item.destination_type === "bybit_uid" ? "Bybit UID" : "USDT TRC20"}<br />{item.destination}</td><td>{item.amount} {item.currency.toUpperCase()}</td><td>{statusLabel(item.status)}</td><td>{item.status === "pending" && <button className={styles.negative} onClick={() => void cancel(item.id)}>Отменить</button>}</td></tr>)}</tbody></table></div>}</div>
    {modal && <div className={styles.modalBackdrop} onMouseDown={() => setModal(false)}><div className={styles.modal} onMouseDown={(e) => e.stopPropagation()}><div className={styles.modalHeader}><h2>Новая заявка</h2><button onClick={() => setModal(false)}>×</button></div><form className={styles.form} onSubmit={create}><label>Сумма USDT<input required type="number" min="0.00000001" step="0.00000001" value={amount} onChange={(e) => setAmount(e.target.value)} /></label><label>Тип назначения<select value={destinationType} onChange={(e) => setDestinationType(e.target.value as MerchantWithdrawal["destination_type"])}><option value="usdt_trc20_address">USDT TRC20</option><option value="bybit_uid">Bybit UID</option></select></label><label>{destinationType === "bybit_uid" ? "Bybit UID" : "TRC20 адрес"}<input required minLength={3} maxLength={255} value={destination} onChange={(e) => setDestination(e.target.value)} /></label><label>Комментарий<input maxLength={500} value={comment} onChange={(e) => setComment(e.target.value)} /></label>{error && <div className={styles.formError}>{error}</div>}<div className={styles.formActions}><button type="button" onClick={() => setModal(false)}>Отмена</button><button disabled={saving}>{saving ? "Создаём…" : "Создать"}</button></div></form></div></div>}
  </section>;
}

function statusLabel(status: MerchantWithdrawal["status"]) { return ({ pending: "Ожидает", approved: "Одобрена", paid: "Выплачена", rejected: "Отклонена", cancelled: "Отменена" } as const)[status]; }
