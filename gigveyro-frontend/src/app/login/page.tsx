"use client";

import { type FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/features/auth/auth-provider";
import { dashboardPath } from "@/features/auth/roles";
import { ApiError } from "@/lib/api/error";
import { ThemeSwitcher } from "@/features/theme/theme-switcher";

import styles from "./page.module.css";

export default function LoginPage() {
  const router = useRouter();
  const { account, login, status } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (status === "authenticated" && account) router.replace(dashboardPath(account.role));
  }, [account, router, status]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const nextAccount = await login({ username: username.trim(), password });
      router.replace(dashboardPath(nextAccount.role));
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Не удалось выполнить вход.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className={styles.page}>
      <section className={styles.panel}>
        <ThemeSwitcher className={styles.themeSwitcher} />
        <div className={styles.brand}>
          <div className={styles.logo}>G</div>
          <div><strong>GIGVEYRO</strong><span>PAYMENT GATEWAY</span></div>
        </div>
        <div className={styles.heading}>
          <span className={styles.eyebrow}>SECURE ACCESS</span>
          <h1>Добро пожаловать</h1>
          <p>Войдите в защищённый кабинет платёжной платформы.</p>
        </div>
        <form className={styles.form} onSubmit={handleSubmit}>
          <label>Логин<input autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required /></label>
          <label>Пароль<input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} /></label>
          {error && <div className={styles.error} role="alert">{error}</div>}
          <button type="submit" disabled={submitting || status === "loading"}>
            {submitting ? "Входим…" : "Войти в кабинет"}
          </button>
        </form>
        <p className={styles.security}>Защищённое соединение · Доступ только для зарегистрированных аккаунтов</p>
      </section>
      <aside className={styles.visual} aria-hidden="true">
        <div className={styles.orbit}><div className={styles.coin}>₮</div></div>
        <p>Fast. Secure. Transparent.</p>
      </aside>
    </main>
  );
}
