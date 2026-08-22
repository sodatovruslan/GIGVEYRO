"use client";

import { type FormEvent, useState } from "react";
import { useTranslations } from "next-intl";

import { useAppFormat } from "@/features/i18n/use-app-format";
import { useEnumLabels } from "@/features/i18n/use-enum-labels";
import { useLocalizedError } from "@/features/i18n/use-localized-error";
import { appealsApi } from "@/lib/api/appeals";
import { dealsApi } from "@/lib/api/deals";
import type { Appeal, AppealReason, UserRole } from "@/lib/api/types";
import { useApiQuery } from "@/lib/hooks/use-api-query";

import styles from "./appeals-page.module.css";

export function AppealsPage({ role }: { role: UserRole }) {
  const t = useTranslations("appeals");
  const common = useTranslations("common");
  const labels = useEnumLabels();
  const format = useAppFormat();
  const localizeError = useLocalizedError();
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

  async function mutate(action: () => Promise<unknown>) { setSaving(true); setError(""); try { await action(); setDialog(null); setSelected(null); setMessage(""); await query.refetch(); } catch (reasonValue) { setError(localizeError(reasonValue)); } finally { setSaving(false); } }
  function openAppeal(event: FormEvent) { event.preventDefault(); void mutate(() => appealsApi.open(dealId, reason, message)); }
  function resolveAppeal(event: FormEvent) { event.preventDefault(); if (selected) void mutate(() => appealsApi.resolve(selected.id, resolution, message)); }

  return <section><div className={styles.heading}><div><span>{t("eyebrow")}</span><h1>{t("title")}</h1><p>{owner ? t("subtitleOwner") : t("subtitleParticipant")}</p></div>{!owner && <button onClick={() => { setDialog("open"); setDealId(deals.data?.items[0]?.id || ""); }}>＋ {t("open")}</button>}</div>{error && <div className={styles.error}>{error}</div>}
    <div className={styles.list}>{query.loading ? <div className={styles.state}>{t("loading")}</div> : query.error ? <div className={`${styles.state} ${styles.errorText}`}>{query.error}</div> : !query.data?.items.length ? <div className={styles.state}>{t("empty")}</div> : query.data.items.map((item) => <article key={item.id}><div className={styles.appealTop}><div><span>{item.public_id}</span><small>{format.dateTime(item.created_at)}</small></div><i className={styles[item.status]}>{labels.appeal(item.status)}</i></div><h2>{labels.appealReason(item.reason_code)}</h2><p>{item.message}</p><dl><div><dt>{t("deal")}</dt><dd>{item.deal_id.slice(0, 8)}…</dd></div><div><dt>{t("openedBy")}</dt><dd>{labels.role(item.opened_by_role)}</dd></div><div><dt>{t("resolution")}</dt><dd>{item.resolution === "settle_to_merchant" ? t("settleMerchant") : item.resolution === "release_to_user" ? t("releaseUser") : "—"}</dd></div></dl>{item.owner_note && <blockquote>{item.owner_note}</blockquote>}<div className={styles.actions}>{owner && item.status === "open" && <button onClick={() => void mutate(() => appealsApi.review(item.id, ""))}>{t("review")}</button>}{owner && ["open", "under_review"].includes(item.status) && <button onClick={() => { setSelected(item); setDialog("resolve"); setMessage(""); }}>{t("resolve")}</button>}{!owner && ["open", "under_review"].includes(item.status) && <button onClick={() => void mutate(() => appealsApi.cancel(item.id))}>{t("cancelAction")}</button>}</div></article>)}</div>
    {dialog === "open" && <Modal title={t("openTitle")} close={() => setDialog(null)}><form onSubmit={openAppeal}><label>{t("deal")}<select required value={dealId} onChange={(event) => setDealId(event.target.value)}><option value="">{t("chooseDeal")}</option>{deals.data?.items.map((deal) => <option value={deal.id} key={deal.id}>{deal.public_id} · {deal.amount_tjs} TJS · {labels.deal(deal.status)}</option>)}</select></label><label>{t("reason")}<select value={reason} onChange={(event) => setReason(event.target.value as AppealReason)}>{(["payment_not_received", "wrong_amount", "payment_proof_issue", "timeout_dispute", "other"] as AppealReason[]).map((value) => <option value={value} key={value}>{labels.appealReason(value)}</option>)}</select></label><label>{t("message")}<textarea required minLength={5} maxLength={2000} value={message} onChange={(event) => setMessage(event.target.value)} /></label>{error && <div className={styles.error}>{error}</div>}<FormActions saving={saving} close={() => setDialog(null)} /></form></Modal>}
    {dialog === "resolve" && <Modal title={t("resolveTitle", { id: selected?.public_id ?? "" })} close={() => setDialog(null)}><form onSubmit={resolveAppeal}><label>{t("resolution")}<select value={resolution} onChange={(event) => setResolution(event.target.value as typeof resolution)}><option value="release_to_user">{t("releaseUser")}</option><option value="settle_to_merchant">{t("settleMerchant")}</option></select></label><label>{t("ownerNote")}<textarea required minLength={3} maxLength={2000} value={message} onChange={(event) => setMessage(event.target.value)} /></label>{error && <div className={styles.error}>{error}</div>}<FormActions saving={saving} close={() => setDialog(null)} /></form></Modal>}
  </section>;

  function FormActions({ saving: isSaving, close }: { saving: boolean; close: () => void }) { return <div className={styles.formActions}><button type="button" onClick={close}>{common("cancel")}</button><button disabled={isSaving}>{isSaving ? common("saving") : common("confirm")}</button></div>; }
}

function Modal({ title, close, children }: { title: string; close: () => void; children: React.ReactNode }) { return <div className={styles.backdrop} onMouseDown={close}><div className={styles.modal} onMouseDown={(event) => event.stopPropagation()}><header><h2>{title}</h2><button onClick={close} aria-label={title}>×</button></header>{children}</div></div>; }
