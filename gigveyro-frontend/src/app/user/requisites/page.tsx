"use client";

import { type FormEvent, useState } from "react";
import { useTranslations } from "next-intl";

import { useLocalizedError } from "@/features/i18n/use-localized-error";
import type { PaymentRequisite } from "@/lib/api/types";
import { userApi, type RequisiteCreateInput } from "@/lib/api/user";
import { useApiQuery } from "@/lib/hooks/use-api-query";

import { PageHeading } from "../user-components";
import styles from "../user.module.css";

const initialForm: RequisiteCreateInput = { type: "bank_card", bank_name: "", holder_name: "", card_number: "", phone_number: null };

export default function UserRequisitesPage() {
  const t = useTranslations("requisites");
  const common = useTranslations("common");
  const localizeError = useLocalizedError();
  const query = useApiQuery(userApi.requisites, "requisites-page");
  const [modalOpen, setModalOpen] = useState(false);
  const [form, setForm] = useState(initialForm);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState<PaymentRequisite | null>(null);
  const [editForm, setEditForm] = useState({ bank_name: "", holder_name: "", phone_number: "" });

  async function submit(event: FormEvent) { event.preventDefault(); setSaving(true); setError(""); try { await userApi.createRequisite({ ...form, phone_number: form.phone_number || null }); setForm(initialForm); setModalOpen(false); await query.refetch(); } catch (reason) { setError(localizeError(reason)); } finally { setSaving(false); } }
  async function action(id: string, nextAction: "activate" | "deactivate" | "archive") { setError(""); try { await userApi.requisiteAction(id, nextAction); await query.refetch(); } catch (reason) { setError(localizeError(reason)); } }
  function openEdit(item: PaymentRequisite) { setError(""); setEditing(item); setEditForm({ bank_name: item.bank_name, holder_name: item.holder_name, phone_number: item.phone_number || "" }); }
  async function update(event: FormEvent) { event.preventDefault(); if (!editing) return; setSaving(true); setError(""); try { await userApi.updateRequisite(editing.id, { ...editForm, phone_number: editForm.phone_number || null }); setEditing(null); await query.refetch(); } catch (reason) { setError(localizeError(reason)); } finally { setSaving(false); } }

  return <section>
    <div className={styles.contentHeader} style={{ padding: 0, border: 0, marginBottom: 27 }}><PageHeading eyebrow={t("eyebrow")} title={t("title")} text={t("subtitle")} /><button className={styles.primaryButton} onClick={() => setModalOpen(true)}>＋ {t("add")}</button></div>
    {error && <div className={styles.inlineError}>{error}</div>}
    {query.loading ? <div className={styles.state}>{t("loading")}</div> : query.error ? <div className={`${styles.state} ${styles.errorText}`}>{query.error}</div> : !query.data?.filter((item) => !item.is_archived).length ? <div className={styles.contentCard}><div className={styles.state}>{t("first")}</div></div> : <div className={styles.requisiteGrid}>{query.data.filter((item) => !item.is_archived).map((item) => <article className={styles.requisiteCard} key={item.id}><div className={styles.requisiteTop}><span>{item.bank_name.toUpperCase()}</span><i>{item.is_active ? common("active") : common("inactive")}</i></div><h3>{item.masked_card_number}</h3><p>{item.holder_name}</p><small>{item.phone_number || t("phoneMissing")}</small><div className={styles.cardActions}><button onClick={() => openEdit(item)}>{common("edit")}</button><button onClick={() => void action(item.id, item.is_active ? "deactivate" : "activate")}>{item.is_active ? t("deactivate") : t("activate")}</button><button onClick={() => void action(item.id, "archive")}>{t("archive")}</button></div></article>)}</div>}
    {modalOpen && <Modal title={t("addTitle")} close={() => setModalOpen(false)}><form className={styles.form} onSubmit={submit}><label>{t("bank")}<input required maxLength={255} value={form.bank_name} onChange={(event) => setForm({ ...form, bank_name: event.target.value })} /></label><label>{t("holder")}<input required maxLength={255} value={form.holder_name} onChange={(event) => setForm({ ...form, holder_name: event.target.value })} /></label><label>{t("cardNumber")}<input required inputMode="numeric" autoComplete="cc-number" minLength={8} maxLength={32} value={form.card_number} onChange={(event) => setForm({ ...form, card_number: event.target.value })} placeholder="0000 0000 0000 0000" /></label><label>{t("phone")}<input maxLength={32} value={form.phone_number || ""} onChange={(event) => setForm({ ...form, phone_number: event.target.value })} /></label>{error && <div className={styles.formError}>{error}</div>}<div className={styles.formActions}><button type="button" onClick={() => setModalOpen(false)}>{common("cancel")}</button><button disabled={saving}>{saving ? t("adding") : t("addAction")}</button></div></form></Modal>}
    {editing && <Modal title={t("editTitle")} close={() => setEditing(null)} subtitle={editing.masked_card_number}><form className={styles.form} onSubmit={update}><label>{t("bank")}<input required maxLength={255} value={editForm.bank_name} onChange={(event) => setEditForm({ ...editForm, bank_name: event.target.value })} /></label><label>{t("holder")}<input required maxLength={255} value={editForm.holder_name} onChange={(event) => setEditForm({ ...editForm, holder_name: event.target.value })} /></label><label>{t("phone")}<input maxLength={32} value={editForm.phone_number} onChange={(event) => setEditForm({ ...editForm, phone_number: event.target.value })} /></label>{error && <div className={styles.formError}>{error}</div>}<div className={styles.formActions}><button type="button" onClick={() => setEditing(null)}>{common("cancel")}</button><button disabled={saving}>{saving ? common("saving") : common("save")}</button></div></form></Modal>}
  </section>;
}

function Modal({ title, subtitle, close, children }: { title: string; subtitle?: string; close: () => void; children: React.ReactNode }) { return <div className={styles.modalBackdrop} onMouseDown={close}><div className={styles.modal} onMouseDown={(event) => event.stopPropagation()}><div className={styles.modalHeader}><div><h2>{title}</h2>{subtitle && <small>{subtitle}</small>}</div><button onClick={close} aria-label={title}>×</button></div>{children}</div></div>; }
