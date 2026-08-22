"use client";

import { type FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { useAuth } from "@/features/auth/auth-provider";
import { loginErrorKey } from "@/features/auth/login-error";
import { dashboardPath } from "@/features/auth/roles";
import { ApiError } from "@/lib/api/error";
import { ThemeSwitcher } from "@/features/theme/theme-switcher";
import { LanguageSwitcher } from "@/features/i18n/language-switcher";
import { useLocalizedError } from "@/features/i18n/use-localized-error";

import styles from "./page.module.css";

function twoFactorErrorKey(reason: unknown) {
  if (reason instanceof ApiError) {
    if (reason.status === 401) return "invalidCode" as const;
    if (reason.status === 410) return "codeExpired" as const;
    if (reason.status === 429) return "tooManyAttempts" as const;
  }
  return null;
}

export default function LoginPage() {
  const router = useRouter();
  const { account, login, verifyTwoFactor, status } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const t = useTranslations("auth");
  const common = useTranslations("common");
  const localizeError = useLocalizedError();

  const [challengeToken, setChallengeToken] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [useRecoveryCode, setUseRecoveryCode] = useState(false);

  useEffect(() => {
    if (status === "authenticated" && account) router.replace(dashboardPath(account.role));
  }, [account, router, status]);

  function resetTwoFactorState() {
    setChallengeToken(null);
    setCode("");
    setUseRecoveryCode(false);
  }

  async function handleCredentialsSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    resetTwoFactorState();
    try {
      const result = await login({ username: username.trim(), password });
      if (result.kind === "two_factor_required") {
        setChallengeToken(result.challengeToken);
        return;
      }
      router.replace(dashboardPath(result.account.role));
    } catch (reason) {
      const authError = loginErrorKey(reason);
      setError(authError ? t(authError) : localizeError(reason));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleCodeSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!challengeToken) return;
    setError("");
    setSubmitting(true);
    try {
      const nextAccount = await verifyTwoFactor(challengeToken, code.trim());
      router.replace(dashboardPath(nextAccount.role));
    } catch (reason) {
      const key = twoFactorErrorKey(reason);
      if (key === "codeExpired") {
        resetTwoFactorState();
        setError(t("codeExpired"));
      } else {
        setError(key ? t(key) : localizeError(reason));
      }
    } finally {
      setSubmitting(false);
    }
  }

  if (challengeToken) {
    return (
      <main className={styles.page}>
        <section className={styles.panel}>
          <div className={styles.preferences}><LanguageSwitcher /><ThemeSwitcher /></div>
          <div className={styles.brand}>
            <div className={styles.logo}>G</div>
            <div><strong>GIGVEYRO</strong><span>{common("paymentGateway")}</span></div>
          </div>
          <div className={styles.heading}>
            <span className={styles.eyebrow}>{t("eyebrow")}</span>
            <h1>{t("twoFactorTitle")}</h1>
            <p>{useRecoveryCode ? t("twoFactorRecoverySubtitle") : t("twoFactorSubtitle")}</p>
          </div>
          <form className={styles.form} onSubmit={handleCodeSubmit}>
            <label>
              {useRecoveryCode ? t("recoveryCodeLabel") : t("verificationCodeLabel")}
              <input
                autoComplete="one-time-code"
                inputMode={useRecoveryCode ? "text" : "numeric"}
                value={code}
                onChange={(e) => { setCode(e.target.value); setError(""); }}
                required
                autoFocus
                maxLength={useRecoveryCode ? 9 : 6}
              />
            </label>
            {error && <div className={styles.error} role="alert">{error}</div>}
            <button type="submit" disabled={submitting}>
              {submitting ? t("verifying") : t("verify")}
            </button>
          </form>
          <p className={styles.security}>
            <button
              type="button"
              className={styles.linkButton}
              onClick={() => { setUseRecoveryCode((v) => !v); setCode(""); setError(""); }}
            >
              {useRecoveryCode ? t("useAuthenticatorCode") : t("useRecoveryCode")}
            </button>
            {" · "}
            <button type="button" className={styles.linkButton} onClick={resetTwoFactorState}>
              {t("backToLogin")}
            </button>
          </p>
        </section>
        <aside className={styles.visual} aria-hidden="true">
          <div className={styles.orbit}><div className={styles.coin}>₮</div></div>
          <p>{common("loginMotto")}</p>
        </aside>
      </main>
    );
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
        <form className={styles.form} onSubmit={handleCredentialsSubmit}>
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
