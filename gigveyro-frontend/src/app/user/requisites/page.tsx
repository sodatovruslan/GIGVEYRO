"use client";

import { type FormEvent, useState } from "react";

import { ApiError } from "@/lib/api/error";
import { userApi, type RequisiteCreateInput } from "@/lib/api/user";
import { useApiQuery } from "@/lib/hooks/use-api-query";

import { PageHeading } from "../user-components";
import styles from "../user.module.css";

const initialForm: RequisiteCreateInput = { type: "bank_card", bank_name: "", holder_name: "", card_number: "", phone_number: null };

export default function UserRequisitesPage() {
  const query = useApiQuery(userApi.requisites, "requisites-page");
  const [modalOpen, setModalOpen] = useState(false);
  const [form, setForm] = useState(initialForm);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault(); setSaving(true); setError("");
    try { await userApi.createRequisite({ ...form, phone_number: form.phone_number || null }); setForm(initialForm); setModalOpen(false); await query.refetch(); }
    catch (reason) { setError(reason instanceof ApiError ? reason.message : "Не удалось создать реквизит."); }
    finally { setSaving(false); }
  }

  async function action(id: string, nextAction: "activate" | "deactivate" | "archive") {
    setError("");
    try { await userApi.requisiteAction(id, nextAction); await query.refetch(); }
    catch (reason) { setError(reason instanceof ApiError ? reason.message : "Не удалось изменить реквизит."); }
  }

  return <section>
    <div className={styles.contentHeader} style={{ padding: 0, border: 0, marginBottom: 27 }}><PageHeading eyebrow="PAYMENT DETAILS" title="Реквизиты" text="Управление банковскими картами для приёма платежей" /><button className={styles.primaryButton} onClick={() => setModalOpen(true)}>＋ Добавить карту</button></div>
    {error && <div className={styles.inlineError}>{error}</div>}
    {query.loading ? <div className={styles.state}>Загружаем реквизиты…</div> : query.error ? <div className={`${styles.state} ${styles.errorText}`}>{query.error}</div> : !query.data?.filter((item) => !item.is_archived).length ? <div className={styles.contentCard}><div className={styles.state}>Добавьте первый банковский реквизит</div></div> : <div className={styles.requisiteGrid}>{query.data.filter((item) => !item.is_archived).map((item) => <article className={styles.requisiteCard} key={item.id}><div className={styles.requisiteTop}><span>{item.bank_name.toUpperCase()}</span><i>{item.is_active ? "ACTIVE" : "INACTIVE"}</i></div><h3>{item.masked_card_number}</h3><p>{item.holder_name}</p><small>{item.phone_number || "Телефон не указан"}</small><div className={styles.cardActions}><button onClick={() => void action(item.id, item.is_active ? "deactivate" : "activate")}>{item.is_active ? "Выключить" : "Включить"}</button><button onClick={() => void action(item.id, "archive")}>Архив</button></div></article>)}</div>}
    {modalOpen && <div className={styles.modalBackdrop} onMouseDown={() => setModalOpen(false)}><div className={styles.modal} onMouseDown={(e) => e.stopPropagation()}><div className={styles.modalHeader}><h2>Добавить банковскую карту</h2><button onClick={() => setModalOpen(false)}>×</button></div><form className={styles.form} onSubmit={submit}><label>Банк<input required maxLength={255} value={form.bank_name} onChange={(e) => setForm({ ...form, bank_name: e.target.value })} /></label><label>Имя владельца<input required maxLength={255} value={form.holder_name} onChange={(e) => setForm({ ...form, holder_name: e.target.value })} /></label><label>Номер карты<input required inputMode="numeric" autoComplete="cc-number" minLength={8} maxLength={32} value={form.card_number} onChange={(e) => setForm({ ...form, card_number: e.target.value })} placeholder="0000 0000 0000 0000" /></label><label>Телефон<input maxLength={32} value={form.phone_number || ""} onChange={(e) => setForm({ ...form, phone_number: e.target.value })} /></label>{error && <div className={styles.formError}>{error}</div>}<div className={styles.formActions}><button type="button" onClick={() => setModalOpen(false)}>Отмена</button><button disabled={saving}>{saving ? "Добавляем…" : "Добавить"}</button></div></form></div></div>}
  </section>;
}
