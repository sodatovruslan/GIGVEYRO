"use client";

import { type FormEvent, useState } from "react";

import { ApiError } from "@/lib/api/error";
import { dealsApi } from "@/lib/api/deals";
import type { Deal, DealStatus, UserRole } from "@/lib/api/types";
import { userApi } from "@/lib/api/user";
import { useApiQuery } from "@/lib/hooks/use-api-query";

import styles from "./deals-page.module.css";

export function DealsPage({ role }: { role: UserRole }) {
  const own = useApiQuery(
    role === "owner" ? dealsApi.ownerList : role === "merchant" ? dealsApi.merchantList : dealsApi.userList,
    `${role}-deals`,
  );
  const available = useApiQuery(dealsApi.available, "available-deals", role === "user");
  const requisites = useApiQuery(userApi.requisites, "deal-requisites", role === "user");
  const [createOpen, setCreateOpen] = useState(false);
  const [acceptDeal, setAcceptDeal] = useState<Deal | null>(null);
  const [amount, setAmount] = useState("");
  const [requisiteId, setRequisiteId] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function mutate(action: () => Promise<unknown>) {
    setSaving(true); setError("");
    try { await action(); setCreateOpen(false); setAcceptDeal(null); setAmount(""); await Promise.all([own.refetch(), ...(role === "user" ? [available.refetch()] : [])]); }
    catch (reason) { setError(reason instanceof ApiError ? reason.message : "Не удалось выполнить действие."); }
    finally { setSaving(false); }
  }

  function create(event: FormEvent) { event.preventDefault(); void mutate(() => dealsApi.merchantCreate(amount)); }
  function accept(event: FormEvent) { event.preventDefault(); if (acceptDeal) void mutate(() => dealsApi.accept(acceptDeal.id, requisiteId)); }
  const activeRequisites = requisites.data?.filter((item) => item.is_active && !item.is_archived) || [];

  return <section>
    <div className={styles.heading}><div><span>DEAL FLOW</span><h1>Сделки</h1><p>{role === "merchant" ? "Создание и контроль платёжных заявок" : role === "user" ? "Доступные и принятые сделки" : "Управление и settlement сделок"}</p></div>{role === "merchant" && <button onClick={() => setCreateOpen(true)}>＋ Создать сделку</button>}</div>
    {error && <div className={styles.error}>{error}</div>}
    {role === "user" && <DealSection title="Доступные сделки" data={available.data?.items} loading={available.loading} error={available.error} empty="Доступных сделок сейчас нет" action={(deal) => <button onClick={() => { setAcceptDeal(deal); setRequisiteId(activeRequisites[0]?.id || ""); }}>Принять</button>} />}
    <DealSection title={role === "user" ? "Мои сделки" : "Все сделки"} data={own.data?.items} loading={own.loading} error={own.error} empty="Сделок пока нет" action={role === "owner" ? (deal) => !["accepted", "payment_pending"].includes(deal.status) ? null : <div className={styles.rowActions}><button disabled={saving} onClick={() => void mutate(() => dealsApi.ownerAction(deal.id, "complete"))}>Завершить</button><button disabled={saving} onClick={() => void mutate(() => dealsApi.ownerAction(deal.id, "release"))}>Release</button></div> : undefined} />
    {createOpen && <Modal title="Создать сделку" close={() => setCreateOpen(false)}><form className={styles.form} onSubmit={create}><label>Сумма TJS<input required type="number" min="0.00000001" step="0.00000001" value={amount} onChange={(e) => setAmount(e.target.value)} /></label><p>Курс и amount USDT рассчитает backend при принятии пользователем.</p>{error && <div className={styles.error}>{error}</div>}<Actions saving={saving} close={() => setCreateOpen(false)} /></form></Modal>}
    {acceptDeal && <Modal title={`Принять ${acceptDeal.public_id}`} close={() => setAcceptDeal(null)}><form className={styles.form} onSubmit={accept}><div className={styles.summary}><span>{acceptDeal.amount_tjs} TJS</span><small>Итоговая сумма USDT появится после ответа backend</small></div><label>Активный реквизит<select required value={requisiteId} onChange={(e) => setRequisiteId(e.target.value)}><option value="">Выберите карту</option>{activeRequisites.map((item) => <option key={item.id} value={item.id}>{item.bank_name} · {item.masked_card_number}</option>)}</select></label>{!activeRequisites.length && <div className={styles.error}>Для принятия сделки нужен активный реквизит.</div>}{error && <div className={styles.error}>{error}</div>}<Actions saving={saving || !activeRequisites.length} close={() => setAcceptDeal(null)} /></form></Modal>}
  </section>;
}

function DealSection({ title, data, loading, error, empty, action }: { title: string; data?: Deal[]; loading: boolean; error: string; empty: string; action?: (deal: Deal) => React.ReactNode }) {
  return <div className={styles.section}><h2>{title}</h2><div className={styles.card}>{loading ? <div className={styles.state}>Загрузка…</div> : error ? <div className={`${styles.state} ${styles.errorText}`}>{error}</div> : !data?.length ? <div className={styles.state}>{empty}</div> : <div className={styles.table}><table><thead><tr><th>ID / создана</th><th>Сумма</th><th>Курс / USDT</th><th>Статус</th><th>Мерчант</th><th>Реквизит</th><th>Срок</th>{action && <th />}</tr></thead><tbody>{data.map((deal) => <tr key={deal.id}><td><strong>{deal.public_id}</strong><small>{formatDate(deal.created_at)}</small></td><td>{deal.amount_tjs} TJS</td><td>{deal.exchange_rate || "—"}<small>{deal.amount_usdt ? `${deal.amount_usdt} USDT` : "Ожидает accept"}</small></td><td><Status status={deal.status} /></td><td><code>{deal.merchant_id.slice(0,8)}</code></td><td>{deal.requisite_bank_name || "—"}<small>{deal.requisite_masked_card_number || "Не назначен"}</small></td><td>{formatDate(deal.expires_at)}<small>{deal.completed_at ? `Завершена ${formatDate(deal.completed_at)}` : deal.accepted_at ? `Принята ${formatDate(deal.accepted_at)}` : ""}</small></td>{action && <td>{action(deal)}</td>}</tr>)}</tbody></table></div>}</div></div>;
}
function Status({ status }: { status: DealStatus }) { return <span className={`${styles.status} ${styles[status]}`}>{status.replace("_", " ")}</span>; }
function Modal({ title, close, children }: { title: string; close: () => void; children: React.ReactNode }) { return <div className={styles.backdrop} onMouseDown={close}><div className={styles.modal} onMouseDown={(e) => e.stopPropagation()}><header><h2>{title}</h2><button onClick={close}>×</button></header>{children}</div></div>; }
function Actions({ saving, close }: { saving: boolean; close: () => void }) { return <div className={styles.actions}><button type="button" onClick={close}>Отмена</button><button disabled={saving}>{saving ? "Выполняем…" : "Подтвердить"}</button></div>; }
function formatDate(value: string) { return new Intl.DateTimeFormat("ru-RU", { dateStyle: "short", timeStyle: "short" }).format(new Date(value)); }
