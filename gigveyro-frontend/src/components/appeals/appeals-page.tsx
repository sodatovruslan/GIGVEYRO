"use client";

import { type FormEvent, useState } from "react";

import { ApiError } from "@/lib/api/error";
import { appealsApi } from "@/lib/api/appeals";
import { dealsApi } from "@/lib/api/deals";
import type { Appeal, AppealReason, UserRole } from "@/lib/api/types";
import { useApiQuery } from "@/lib/hooks/use-api-query";

import styles from "./appeals-page.module.css";

export function AppealsPage({ role }: { role: UserRole }) {
  const owner = role === "owner";
  const query = useApiQuery(() => appealsApi.list(owner), `${role}-appeals`);
  const deals = useApiQuery(role === "merchant" ? dealsApi.merchantList : dealsApi.userList, `${role}-appeal-deals`, !owner);
  const [dialog, setDialog] = useState<"open" | "resolve" | null>(null);
  const [selected, setSelected] = useState<Appeal | null>(null);
  const [dealId, setDealId] = useState("");
  const [reason, setReason] = useState<AppealReason>("payment_not_received");
  const [message, setMessage] = useState("");
  const [resolution, setResolution] = useState<"settle_to_merchant" | "release_to_user">("release_to_user");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function mutate(action: () => Promise<unknown>) { setSaving(true); setError(""); try { await action(); setDialog(null); setSelected(null); setMessage(""); await query.refetch(); } catch (reason) { setError(reason instanceof ApiError ? reason.message : "Не удалось выполнить действие."); } finally { setSaving(false); } }
  function openAppeal(event: FormEvent) { event.preventDefault(); void mutate(() => appealsApi.open(dealId, reason, message)); }
  function resolveAppeal(event: FormEvent) { event.preventDefault(); if (selected) void mutate(() => appealsApi.resolve(selected.id, resolution, message)); }

  return <section><div className={styles.heading}><div><span>DISPUTE CENTER</span><h1>Апелляции</h1><p>{owner ? "Рассмотрение и разрешение спорных сделок" : "Споры по вашим сделкам"}</p></div>{!owner && <button onClick={() => { setDialog("open"); setDealId(deals.data?.items[0]?.id || ""); }}>＋ Открыть апелляцию</button>}</div>{error && <div className={styles.error}>{error}</div>}
    <div className={styles.list}>{query.loading ? <div className={styles.state}>Загрузка…</div> : query.error ? <div className={`${styles.state} ${styles.errorText}`}>{query.error}</div> : !query.data?.items.length ? <div className={styles.state}>Апелляций пока нет</div> : query.data.items.map((item) => <article key={item.id}><div className={styles.appealTop}><div><span>{item.public_id}</span><small>{new Intl.DateTimeFormat("ru-RU",{dateStyle:"medium",timeStyle:"short"}).format(new Date(item.created_at))}</small></div><i className={styles[item.status]}>{item.status.replace("_"," ")}</i></div><h2>{reasonLabel(item.reason_code)}</h2><p>{item.message}</p><dl><div><dt>Deal ID</dt><dd>{item.deal_id.slice(0,8)}…</dd></div><div><dt>Открыл</dt><dd>{item.opened_by_role.toUpperCase()}</dd></div><div><dt>Решение</dt><dd>{item.resolution || "—"}</dd></div></dl>{item.owner_note && <blockquote>{item.owner_note}</blockquote>}<div className={styles.actions}>{owner && item.status === "open" && <button onClick={() => void mutate(() => appealsApi.review(item.id,""))}>Взять в работу</button>}{owner && ["open","under_review"].includes(item.status) && <button onClick={() => {setSelected(item);setDialog("resolve");setMessage("");}}>Разрешить</button>}{!owner && ["open","under_review"].includes(item.status) && <button onClick={() => void mutate(() => appealsApi.cancel(item.id))}>Отменить</button>}</div></article>)}</div>
    {dialog === "open" && <Modal title="Новая апелляция" close={() => setDialog(null)}><form onSubmit={openAppeal}><label>Сделка<select required value={dealId} onChange={(e)=>setDealId(e.target.value)}><option value="">Выберите сделку</option>{deals.data?.items.map((deal)=><option value={deal.id} key={deal.id}>{deal.public_id} · {deal.amount_tjs} TJS · {deal.status}</option>)}</select></label><label>Причина<select value={reason} onChange={(e)=>setReason(e.target.value as AppealReason)}>{(["payment_not_received","wrong_amount","payment_proof_issue","timeout_dispute","other"] as AppealReason[]).map((value)=><option value={value} key={value}>{reasonLabel(value)}</option>)}</select></label><label>Описание<textarea required minLength={5} maxLength={2000} value={message} onChange={(e)=>setMessage(e.target.value)}/></label>{error&&<div className={styles.error}>{error}</div>}<FormActions saving={saving} close={()=>setDialog(null)}/></form></Modal>}
    {dialog === "resolve" && <Modal title={`Решение ${selected?.public_id}`} close={() => setDialog(null)}><form onSubmit={resolveAppeal}><label>Решение<select value={resolution} onChange={(e)=>setResolution(e.target.value as typeof resolution)}><option value="release_to_user">Вернуть пользователю</option><option value="settle_to_merchant">Зачислить мерчанту</option></select></label><label>Комментарий владельца<textarea required minLength={3} maxLength={2000} value={message} onChange={(e)=>setMessage(e.target.value)}/></label>{error&&<div className={styles.error}>{error}</div>}<FormActions saving={saving} close={()=>setDialog(null)}/></form></Modal>}
  </section>;
}

function Modal({title,close,children}:{title:string;close:()=>void;children:React.ReactNode}){return <div className={styles.backdrop} onMouseDown={close}><div className={styles.modal} onMouseDown={(e)=>e.stopPropagation()}><header><h2>{title}</h2><button onClick={close}>×</button></header>{children}</div></div>}
function FormActions({saving,close}:{saving:boolean;close:()=>void}){return <div className={styles.formActions}><button type="button" onClick={close}>Отмена</button><button disabled={saving}>{saving?"Выполняем…":"Подтвердить"}</button></div>}
function reasonLabel(reason:AppealReason){return ({payment_not_received:"Платёж не получен",wrong_amount:"Неверная сумма",payment_proof_issue:"Проблема с подтверждением",timeout_dispute:"Спор по таймауту",other:"Другая причина"} as const)[reason]}
