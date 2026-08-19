"use client";

import { type FormEvent, useState } from "react";

import { ownerOperationsApi } from "@/lib/api/owner-operations";
import { useApiQuery } from "@/lib/hooks/use-api-query";

import { Heading } from "../owner-components";
import styles from "../operations.module.css";

interface Filters { actorAccountId: string; action: string; entityType: string; offset: number }
const emptyFilters: Filters = { actorAccountId: "", action: "", entityType: "", offset: 0 };

export default function AuditPage() {
  const [draft, setDraft] = useState(emptyFilters);
  const [filters, setFilters] = useState(emptyFilters);
  const key = JSON.stringify(filters);
  const query = useApiQuery(() => ownerOperationsApi.auditLogs(filters), `audit:${key}`);
  function apply(event: FormEvent) { event.preventDefault(); setFilters({ ...draft, offset: 0 }); }
  function page(offset: number) { const next = { ...filters, offset }; setFilters(next); setDraft(next); }
  return <section><Heading title="Журнал аудита" text="Неизменяемая история административных и системных действий" />
    <form className={styles.toolbar} onSubmit={apply}><input aria-label="ID аккаунта" placeholder="ID аккаунта" value={draft.actorAccountId} onChange={(e) => setDraft({ ...draft, actorAccountId: e.target.value })} /><input aria-label="Действие" placeholder="Действие" value={draft.action} onChange={(e) => setDraft({ ...draft, action: e.target.value })} /><input aria-label="Тип сущности" placeholder="Тип сущности" value={draft.entityType} onChange={(e) => setDraft({ ...draft, entityType: e.target.value })} /><button>Применить</button></form>
    {query.error && <div className={styles.error}>{query.error}</div>}
    <div className={styles.card}>{query.loading ? <div className={styles.state}>Загружаем журнал…</div> : !query.data?.items.length ? <div className={styles.state}>Записей не найдено</div> : <><div className={styles.table}><table><thead><tr><th>Дата</th><th>Действие</th><th>Сущность</th><th>Инициатор</th><th>Request ID</th></tr></thead><tbody>{query.data.items.map((item) => <tr key={item.id}><td>{formatDate(item.created_at)}</td><td><strong>{item.action}</strong></td><td>{item.entity_type}<small>{item.entity_id || "—"}</small></td><td>{item.actor_role || "system"}<small>{item.actor_account_id || "—"}</small></td><td><code>{item.request_id || "—"}</code></td></tr>)}</tbody></table></div><div className={styles.pager}><span>{filters.offset + 1}–{Math.min(filters.offset + query.data.limit, query.data.total)} из {query.data.total}</span><button disabled={filters.offset === 0} onClick={() => page(Math.max(0, filters.offset - 50))}>Назад</button><button disabled={filters.offset + query.data.limit >= query.data.total} onClick={() => page(filters.offset + 50)}>Далее</button></div></>}</div>
  </section>;
}
function formatDate(value: string) { return new Intl.DateTimeFormat("ru-RU", { dateStyle: "short", timeStyle: "medium" }).format(new Date(value)); }
