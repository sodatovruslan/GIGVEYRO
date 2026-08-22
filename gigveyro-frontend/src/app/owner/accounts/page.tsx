"use client";

import Link from "next/link";
import { type FormEvent, useState } from "react";
import { useTranslations } from "next-intl";

import { useAppFormat } from "@/features/i18n/use-app-format";
import { useEnumLabels } from "@/features/i18n/use-enum-labels";
import { useLocalizedError } from "@/features/i18n/use-localized-error";
import { ownerAccountsApi, type CreateAccountInput } from "@/lib/api/owner-accounts";
import type { UserRole } from "@/lib/api/types";
import { useApiQuery } from "@/lib/hooks/use-api-query";

import styles from "./accounts.module.css";

const emptyForm: CreateAccountInput = { username: "", password: "", role: "user", full_name: "", email: null, phone: null };

export default function OwnerAccountsPage() {
  const t = useTranslations("accounts");
  const common = useTranslations("common");
  const labels = useEnumLabels();
  const format = useAppFormat();
  const localizeError = useLocalizedError();
  const [search, setSearch] = useState("");
  const [role, setRole] = useState<UserRole | "">("");
  const [modalOpen, setModalOpen] = useState(false);
  const [form, setForm] = useState<CreateAccountInput>(emptyForm);
  const [formError, setFormError] = useState("");
  const [saving, setSaving] = useState(false);
  const { data, loading, error, refetch } = useApiQuery(() => ownerAccountsApi.list({ search: search.trim(), role, limit: 100 }), `accounts:${search}:${role}`);

  async function createAccount(event: FormEvent) { event.preventDefault(); setSaving(true); setFormError(""); try { await ownerAccountsApi.create({ ...form, email: form.email || null, phone: form.phone || null }); setForm(emptyForm); setModalOpen(false); await refetch(); } catch (reason) { setFormError(localizeError(reason)); } finally { setSaving(false); } }

  return <section>
    <div className={styles.pageHeader}><div><span>{t("eyebrow")}</span><h1>{t("title")}</h1><p>{t("subtitle")}</p></div><button className={styles.primaryButton} onClick={() => setModalOpen(true)}>＋ {t("create")}</button></div>
    <div className={styles.toolbar}><label className={styles.search}><span>⌕</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t("searchPlaceholder")} /></label><select value={role} onChange={(event) => setRole(event.target.value as UserRole | "")}><option value="">{t("allRoles")}</option><option value="user">{labels.role("user")}</option><option value="merchant">{labels.role("merchant")}</option></select><div className={styles.total}>{t("total")}: <strong>{data?.total ?? "—"}</strong></div></div>
    <div className={styles.tableCard}>{loading ? <div className={styles.state}>{t("loading")}</div> : error ? <div className={`${styles.state} ${styles.error}`}>{error}<button onClick={refetch}>{common("retry")}</button></div> : !data?.items.length ? <div className={styles.state}>{t("empty")}</div> : <div className={styles.tableScroll}><table><thead><tr><th>{t("title")}</th><th>{t("role")}</th><th>{t("contacts")}</th><th>{common("status")}</th><th>{t("created")}</th><th /></tr></thead><tbody>{data.items.map((account) => <tr key={account.id}><td><div className={styles.accountCell}><span>{account.full_name.slice(0, 1).toUpperCase()}</span><div><strong>{account.full_name}</strong><small>@{account.username}</small></div></div></td><td><span className={`${styles.badge} ${account.role === "merchant" ? styles.merchant : styles.user}`}>{labels.role(account.role)}</span></td><td><div className={styles.contacts}><span>{account.email || t("emailMissing")}</span><small>{account.phone || t("phoneMissing")}</small></div></td><td><span className={`${styles.status} ${account.is_active ? styles.active : styles.blocked}`}><i />{account.is_active ? common("active") : t("blocked")}</span></td><td>{format.date(account.created_at)}</td><td><Link className={styles.openButton} href={`/owner/accounts/${account.id}`}>{t("open")} →</Link></td></tr>)}</tbody></table></div>}</div>
    {modalOpen && <div className={styles.modalBackdrop} onMouseDown={() => setModalOpen(false)}><div className={styles.modal} role="dialog" aria-modal="true" aria-labelledby="create-title" onMouseDown={(event) => event.stopPropagation()}><div className={styles.modalHeader}><div><span>{t("newEyebrow")}</span><h2 id="create-title">{t("createTitle")}</h2></div><button onClick={() => setModalOpen(false)} aria-label={t("close")}>×</button></div><form onSubmit={createAccount} className={styles.form}><label>{t("role")}<select value={form.role} onChange={(event) => setForm({ ...form, role: event.target.value as "user" | "merchant" })}><option value="user">{labels.role("user")}</option><option value="merchant">{labels.role("merchant")}</option></select></label><div className={styles.formGrid}><label>{t("username")}<input required maxLength={50} value={form.username} onChange={(event) => setForm({ ...form, username: event.target.value })} /></label><label>{t("fullName")}<input required maxLength={255} value={form.full_name} onChange={(event) => setForm({ ...form, full_name: event.target.value })} /></label></div><label>{t("password")}<input required type="password" minLength={8} maxLength={128} autoComplete="new-password" value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} /></label><div className={styles.formGrid}><label>{t("email")}<input type="email" value={form.email || ""} onChange={(event) => setForm({ ...form, email: event.target.value })} /></label><label>{t("phone")}<input value={form.phone || ""} onChange={(event) => setForm({ ...form, phone: event.target.value })} /></label></div>{formError && <div className={styles.formError}>{formError}</div>}<div className={styles.formActions}><button type="button" onClick={() => setModalOpen(false)}>{common("cancel")}</button><button className={styles.primaryButton} disabled={saving}>{saving ? t("creating") : common("create")}</button></div></form></div></div>}
  </section>;
}
