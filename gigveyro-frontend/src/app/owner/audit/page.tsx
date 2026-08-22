"use client";

import { type FormEvent, useState } from "react";
import { useTranslations } from "next-intl";

import { auditMessagePath, type AuditMessageKind } from "@/features/audit/i18n";
import { useAppFormat } from "@/features/i18n/use-app-format";
import { auditActions, auditEntityTypes, ownerOperationsApi } from "@/lib/api/owner-operations";
import { useApiQuery } from "@/lib/hooks/use-api-query";
import { Heading } from "../owner-components";
import styles from "../operations.module.css";

interface Filters { actorAccountId: string; action: string; entityType: string; offset: number }
const emptyFilters: Filters = { actorAccountId: "", action: "", entityType: "", offset: 0 };

export default function AuditPage() {
  const t = useTranslations("audit"); const common = useTranslations("common"); const format = useAppFormat();
  const [draft, setDraft] = useState(emptyFilters); const [filters, setFilters] = useState(emptyFilters);
  const query = useApiQuery(() => ownerOperationsApi.auditLogs(filters), `audit:${JSON.stringify(filters)}`);
  function apply(event: FormEvent) { event.preventDefault(); setFilters({ ...draft, offset: 0 }); }
  function reset() { setDraft(emptyFilters); setFilters(emptyFilters); }
  function page(offset: number) { const next = { ...filters, offset }; setFilters(next); setDraft(next); }
  const label = (kind: AuditMessageKind, value: string) => {
    const path = auditMessagePath(kind, value);
    return path && t.has(path) ? t(path) : value;
  };
  return <section><Heading title={t("title")} text={t("subtitle")} /><form className={styles.toolbar} onSubmit={apply}><input aria-label={t("accountId")} placeholder={t("accountId")} value={draft.actorAccountId} onChange={(event) => setDraft({ ...draft, actorAccountId: event.target.value })} /><select aria-label={t("action")} value={draft.action} onChange={(event) => setDraft({ ...draft, action: event.target.value })}><option value="">{t("allActions")}</option>{auditActions.map((value) => <option value={value} key={value}>{label("actions", value)}</option>)}</select><select aria-label={t("entityType")} value={draft.entityType} onChange={(event) => setDraft({ ...draft, entityType: event.target.value })}><option value="">{t("allEntities")}</option>{auditEntityTypes.map((value) => <option value={value} key={value}>{label("entities", value)}</option>)}</select><button>{t("apply")}</button><button type="button" className={styles.secondary} onClick={reset}>{t("reset")}</button></form>{query.error && <div className={styles.error}>{query.error}</div>}<div className={styles.card}>{query.loading ? <div className={styles.state}>{t("loading")}</div> : !query.data?.items.length ? <div className={styles.state}>{t("empty")}</div> : <><div className={styles.table}><table><thead><tr><th>{common("date")}</th><th>{t("action")}</th><th>{t("entity")}</th><th>{t("actor")}</th><th>{t("requestId")}</th></tr></thead><tbody>{query.data.items.map((item) => <tr key={item.id}><td>{format.dateTime(item.created_at)}</td><td><strong>{label("actions", item.action)}</strong><small>{item.action}</small></td><td>{label("entities", item.entity_type)}<small>{item.entity_id || "—"}</small></td><td>{item.actor_role || common("system")}<small>{item.actor_account_id || "—"}</small></td><td><code>{item.request_id || "—"}</code></td></tr>)}</tbody></table></div><div className={styles.pager}><span>{common("fromTotal", { from: filters.offset + 1, to: Math.min(filters.offset + query.data.limit, query.data.total), total: query.data.total })}</span><button disabled={filters.offset === 0} onClick={() => page(Math.max(0, filters.offset - 50))}>{common("back")}</button><button disabled={filters.offset + query.data.limit >= query.data.total} onClick={() => page(filters.offset + 50)}>{common("next")}</button></div></>}</div></section>;
}
