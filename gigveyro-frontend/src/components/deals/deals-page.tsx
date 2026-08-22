"use client";

import Link from "next/link";
import { type FormEvent, useState } from "react";
import { useTranslations } from "next-intl";

import { DealDetailGrid } from "./deal-detail";
import { useAppFormat } from "@/features/i18n/use-app-format";
import { useEnumLabels } from "@/features/i18n/use-enum-labels";
import { useLocalizedError } from "@/features/i18n/use-localized-error";
import { dealsApi } from "@/lib/api/deals";
import type { Deal, UserRole } from "@/lib/api/types";
import { userApi } from "@/lib/api/user";
import { useApiQuery } from "@/lib/hooks/use-api-query";

import styles from "./deals-page.module.css";

export function DealsPage({ role }: { role: UserRole }) {
  const t = useTranslations("deals");
  const common = useTranslations("common");
  const format = useAppFormat();
  const labels = useEnumLabels();
  const localizeError = useLocalizedError();
  const own = useApiQuery(role === "owner" ? dealsApi.ownerList : role === "merchant" ? dealsApi.merchantList : dealsApi.userList, `${role}-deals`);
  const available = useApiQuery(dealsApi.available, "available-deals", role === "user");
  const requisites = useApiQuery(userApi.requisites, "deal-requisites", role === "user");
  const [createOpen, setCreateOpen] = useState(false);
  const [acceptDeal, setAcceptDeal] = useState<Deal | null>(null);
  const [amount, setAmount] = useState("");
  const [requisiteId, setRequisiteId] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [detail, setDetail] = useState<Deal | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");

  async function openDetail(id: string) {
    setDetail(null); setDetailError(""); setDetailLoading(true);
    try { setDetail(await (role === "merchant" ? dealsApi.merchantGet(id) : dealsApi.userGet(id))); }
    catch (reason) { setDetailError(localizeError(reason)); }
    finally { setDetailLoading(false); }
  }
  function closeDetail() { setDetail(null); setDetailError(""); }

  async function mutate(action: () => Promise<unknown>, closeOnError = false) {
    setSaving(true); setError("");
    try { await action(); setCreateOpen(false); setAcceptDeal(null); setAmount(""); await Promise.all([own.refetch(), ...(role === "user" ? [available.refetch()] : [])]); }
    catch (reason) {
      setError(localizeError(reason));
      if (closeOnError) setAcceptDeal(null);
      // The deal's real state may have changed underneath us (already accepted,
      // no longer available, etc) - refetch so stale action buttons disappear.
      await Promise.all([own.refetch(), ...(role === "user" ? [available.refetch()] : [])]);
    }
    finally { setSaving(false); }
  }

  function create(event: FormEvent) { event.preventDefault(); void mutate(() => dealsApi.merchantCreate(amount)); }
  function accept(event: FormEvent) { event.preventDefault(); if (acceptDeal) void mutate(() => dealsApi.accept(acceptDeal.id, requisiteId), true); }
  const activeRequisites = requisites.data?.filter((item) => item.is_active && !item.is_archived) || [];
  const subtitle = role === "merchant" ? t("merchantSubtitle") : role === "user" ? t("userSubtitle") : t("ownerSubtitle");

  return <section>
    <div className={styles.heading}><div><span>{t("eyebrow")}</span><h1>{t("title")}</h1><p>{subtitle}</p></div>{role === "merchant" && <button onClick={() => setCreateOpen(true)}>＋ {t("create")}</button>}</div>
    {error && <div className={styles.error}>{error}</div>}
    {role === "user" && <DealSection title={t("available")} data={available.data?.items} loading={available.loading} error={available.error} empty={t("emptyAvailable")} action={(deal) => <button onClick={() => { setAcceptDeal(deal); setRequisiteId(activeRequisites[0]?.id || ""); }}>{t("accept")}</button>} />}
    <DealSection title={role === "user" ? t("own") : t("all")} data={own.data?.items} loading={own.loading} error={own.error} empty={role === "owner" ? t("emptyOwner") : role === "merchant" ? t("emptyMerchant") : t("emptyOwn")} action={role === "owner" ? (deal) => !["accepted", "payment_pending"].includes(deal.status) ? null : <div className={styles.rowActions}><button disabled={saving} onClick={() => void mutate(() => dealsApi.ownerAction(deal.id, "complete"))}>{t("complete")}</button><button disabled={saving} onClick={() => void mutate(() => dealsApi.ownerAction(deal.id, "release"))}>{t("release")}</button></div> : undefined} onRowClick={role !== "owner" ? (deal) => void openDetail(deal.id) : undefined} ownerDetailBase={role === "owner" ? "/owner/deals" : undefined} />
    {createOpen && <Modal title={t("createTitle")} close={() => setCreateOpen(false)}><form className={styles.form} onSubmit={create}><label>{t("amountTjs")}<input required type="number" min="0.00000001" step="0.00000001" value={amount} onChange={(event) => setAmount(event.target.value)} /></label><p>{t("backendCalculation")}</p>{error && <div className={styles.error}>{error}</div>}<Actions saving={saving} close={() => setCreateOpen(false)} /></form></Modal>}
    {acceptDeal && <Modal title={t("acceptTitle", { id: acceptDeal.public_id })} close={() => setAcceptDeal(null)}><form className={styles.form} onSubmit={accept}><div className={styles.summary}><span>{acceptDeal.amount_tjs} TJS</span><small>{t("backendCalculation")}</small></div><label>{t("requisite")}<select required value={requisiteId} onChange={(event) => setRequisiteId(event.target.value)}><option value="">{t("chooseRequisite")}</option>{activeRequisites.map((item) => <option key={item.id} value={item.id}>{item.bank_name} · {item.masked_card_number}</option>)}</select></label>{!activeRequisites.length && <div className={styles.error}>{t("noActiveRequisites")}</div>}{error && <div className={styles.error}>{error}</div>}<Actions saving={saving || !activeRequisites.length} close={() => setAcceptDeal(null)} /></form></Modal>}
    {(detailLoading || detail || detailError) && <Modal title={t("detailTitle")} close={closeDetail}>{detailLoading ? <p>{t("loading")}</p> : detailError ? <div className={styles.error}>{detailError}</div> : detail && <DealDetailGrid deal={detail} />}</Modal>}
  </section>;

  function DealSection({ title, data, loading, error: sectionError, empty, action, onRowClick, ownerDetailBase }: { title: string; data?: Deal[]; loading: boolean; error: string; empty: string; action?: (deal: Deal) => React.ReactNode; onRowClick?: (deal: Deal) => void; ownerDetailBase?: string }) {
    return <div className={styles.section}><h2>{title}</h2><div className={styles.card}>{loading ? <div className={styles.state}>{t("loading")}</div> : sectionError ? <div className={`${styles.state} ${styles.errorText}`}>{sectionError}</div> : !data?.length ? <div className={styles.state}>{empty}</div> : <div className={styles.table}><table><thead><tr><th>ID / {t("created")}</th><th>{common("amount")}</th><th>{t("rate")}</th><th>{common("status")}</th><th>{t("merchant")}</th><th>{t("requisite")}</th><th>{t("deadline")}</th>{action && <th />}</tr></thead><tbody>{data.map((deal) => <tr key={deal.id} className={onRowClick ? styles.row : undefined} onClick={onRowClick ? () => onRowClick(deal) : undefined}><td>{ownerDetailBase ? <Link href={`${ownerDetailBase}/${deal.id}`} className={styles.rowLink}><strong>{deal.public_id}</strong></Link> : <strong>{deal.public_id}</strong>}<small>{format.dateTime(deal.created_at)}</small></td><td>{deal.amount_tjs} TJS</td><td>{deal.exchange_rate || "—"}<small>{deal.amount_usdt ? `${deal.amount_usdt} USDT` : labels.deal(deal.status)}</small></td><td><span className={`${styles.status} ${styles[deal.status]}`}>{labels.deal(deal.status)}</span></td><td><code>{deal.merchant_id.slice(0, 8)}</code></td><td>{deal.requisite_bank_name || "—"}<small>{deal.requisite_masked_card_number || common("notSpecified")}</small></td><td>{format.dateTime(deal.expires_at)}<small>{deal.completed_at ? `${t("completed")} ${format.dateTime(deal.completed_at)}` : deal.accepted_at ? `${t("accepted")} ${format.dateTime(deal.accepted_at)}` : ""}</small></td>{action && <td onClick={(event) => event.stopPropagation()}>{action(deal)}</td>}</tr>)}</tbody></table></div>}</div></div>;
  }

  function Actions({ saving: isSaving, close }: { saving: boolean; close: () => void }) { return <div className={styles.actions}><button type="button" onClick={close}>{common("cancel")}</button><button disabled={isSaving}>{isSaving ? common("saving") : common("confirm")}</button></div>; }
}

function Modal({ title, close, children }: { title: string; close: () => void; children: React.ReactNode }) { return <div className={styles.backdrop} onMouseDown={close}><div className={styles.modal} onMouseDown={(event) => event.stopPropagation()}><header><h2>{title}</h2><button onClick={close} aria-label={title}>×</button></header>{children}</div></div>; }
