"use client";

import Link from "next/link";
import { type FormEvent, useState } from "react";

import { ApiError } from "@/lib/api/error";
import { ownerAccountsApi, type CreateAccountInput } from "@/lib/api/owner-accounts";
import type { UserRole } from "@/lib/api/types";
import { useApiQuery } from "@/lib/hooks/use-api-query";

import styles from "./accounts.module.css";

const emptyForm: CreateAccountInput = {
  username: "", password: "", role: "user", full_name: "", email: null, phone: null,
};

export default function OwnerAccountsPage() {
  const [search, setSearch] = useState("");
  const [role, setRole] = useState<UserRole | "">("");
  const [modalOpen, setModalOpen] = useState(false);
  const [form, setForm] = useState<CreateAccountInput>(emptyForm);
  const [formError, setFormError] = useState("");
  const [saving, setSaving] = useState(false);
  const { data, loading, error, refetch } = useApiQuery(
    () => ownerAccountsApi.list({ search: search.trim(), role, limit: 100 }),
    `accounts:${search}:${role}`,
  );

  async function createAccount(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setFormError("");
    try {
      await ownerAccountsApi.create({ ...form, email: form.email || null, phone: form.phone || null });
      setForm(emptyForm);
      setModalOpen(false);
      await refetch();
    } catch (reason) {
      setFormError(reason instanceof ApiError ? reason.message : "Не удалось создать аккаунт.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section>
      <div className={styles.pageHeader}>
        <div><span>ACCOUNT MANAGEMENT</span><h1>Аккаунты</h1><p>Пользователи и мерчанты платформы</p></div>
        <button className={styles.primaryButton} onClick={() => setModalOpen(true)}>＋ Создать аккаунт</button>
      </div>
      <div className={styles.toolbar}>
        <label className={styles.search}><span>⌕</span><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Поиск по логину, имени, email…" /></label>
        <select value={role} onChange={(e) => setRole(e.target.value as UserRole | "")}>
          <option value="">Все роли</option><option value="user">Пользователи</option><option value="merchant">Мерчанты</option>
        </select>
        <div className={styles.total}>Всего: <strong>{data?.total ?? "—"}</strong></div>
      </div>
      <div className={styles.tableCard}>
        {loading ? <div className={styles.state}>Загружаем аккаунты…</div> : error ? <div className={`${styles.state} ${styles.error}`}>{error}<button onClick={refetch}>Повторить</button></div> : !data?.items.length ? <div className={styles.state}>Аккаунты не найдены</div> : (
          <div className={styles.tableScroll}><table><thead><tr><th>Аккаунт</th><th>Роль</th><th>Контакты</th><th>Статус</th><th>Создан</th><th /></tr></thead><tbody>
            {data.items.map((account) => <tr key={account.id}>
              <td><div className={styles.accountCell}><span>{account.full_name.slice(0, 1).toUpperCase()}</span><div><strong>{account.full_name}</strong><small>@{account.username}</small></div></div></td>
              <td><span className={`${styles.badge} ${account.role === "merchant" ? styles.merchant : styles.user}`}>{account.role === "merchant" ? "MERCHANT" : account.role === "user" ? "USER" : "OWNER"}</span></td>
              <td><div className={styles.contacts}><span>{account.email || "Email не указан"}</span><small>{account.phone || "Телефон не указан"}</small></div></td>
              <td><span className={`${styles.status} ${account.is_active ? styles.active : styles.blocked}`}><i />{account.is_active ? "Активен" : "Заблокирован"}</span></td>
              <td>{new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium" }).format(new Date(account.created_at))}</td>
              <td><Link className={styles.openButton} href={`/owner/accounts/${account.id}`}>Открыть →</Link></td>
            </tr>)}
          </tbody></table></div>
        )}
      </div>
      {modalOpen && <div className={styles.modalBackdrop} onMouseDown={() => setModalOpen(false)}>
        <div className={styles.modal} role="dialog" aria-modal="true" aria-labelledby="create-title" onMouseDown={(e) => e.stopPropagation()}>
          <div className={styles.modalHeader}><div><span>NEW ACCOUNT</span><h2 id="create-title">Создать аккаунт</h2></div><button onClick={() => setModalOpen(false)} aria-label="Закрыть">×</button></div>
          <form onSubmit={createAccount} className={styles.form}>
            <label>Роль<select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as "user" | "merchant" })}><option value="user">USER</option><option value="merchant">MERCHANT</option></select></label>
            <div className={styles.formGrid}><label>Логин<input required maxLength={50} value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} /></label><label>Полное имя<input required maxLength={255} value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></label></div>
            <label>Пароль<input required type="password" minLength={8} maxLength={128} autoComplete="new-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></label>
            <div className={styles.formGrid}><label>Email<input type="email" value={form.email || ""} onChange={(e) => setForm({ ...form, email: e.target.value })} /></label><label>Телефон<input value={form.phone || ""} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></label></div>
            {formError && <div className={styles.formError}>{formError}</div>}
            <div className={styles.formActions}><button type="button" onClick={() => setModalOpen(false)}>Отмена</button><button className={styles.primaryButton} disabled={saving}>{saving ? "Создаём…" : "Создать"}</button></div>
          </form>
        </div>
      </div>}
    </section>
  );
}
