"use client";

import { type FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { useAuth } from "@/features/auth/auth-provider";
import { loginErrorKey } from "@/features/auth/login-error";
import { dashboardPath } from "@/features/auth/roles";
import { ThemeSwitcher } from "@/features/theme/theme-switcher";
import { LanguageSwitcher } from "@/features/i18n/language-switcher";
import { useLocalizedError } from "@/features/i18n/use-localized-error";

import styles from "./page.module.css";

export default function LoginPage() {
  const router = useRouter();
  const { account, login, status } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const t = useTranslations("auth");
  const common = useTranslations("common");
  const localizeError = useLocalizedError();

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
      const authError = loginErrorKey(reason);
      setError(authError ? t(authError) : localizeError(reason));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className={styles.page}>
      <section className={styles.panel}>
        <div className={styles.preferences}><LanguageSwitcher /><ThemeSwitcher /></div>
        <div className={styles.brand}>
          <div className={styles.logo}>G</div>
          <div><strong>GIGVEYRO</strong><span>{common("paymentGateway")}</span></div>
        </div>
        <div className={styles.heading}>
          <span className={styles.eyebrow}>{t("eyebrow")}</span><h1>{t("welcome")}</h1><p>{t("subtitle")}</p>
        </div>
        <form className={styles.form} onSubmit={handleSubmit}>
          <label>{t("username")}<input autoComplete="username" value={username} onChange={(e) => { setUsername(e.target.value); setError(""); }} required /></label><label>{t("password")}<input type="password" autoComplete="current-password" value={password} onChange={(e) => { setPassword(e.target.value); setError(""); }} required minLength={8} /></label>
          {error && <div className={styles.error} role="alert">{error}</div>}
          <button type="submit" disabled={submitting || status === "loading"}>
            {submitting ? t("submitting") : t("submit")}
          </button>
        </form>
        <p className={styles.security}>{t("security")}</p>
      </section>
      <aside className={styles.visual} aria-hidden="true">
        <div className={styles.orbit}><div className={styles.coin}>₮</div></div>
        <p>{common("loginMotto")}</p>
      </aside>
    </main>
  );
}
