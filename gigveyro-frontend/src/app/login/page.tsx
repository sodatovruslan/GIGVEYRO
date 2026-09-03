"use client";

import { type FormEvent, useEffect, useState } from "react";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import QRCode from "qrcode";

import { useAuth } from "@/features/auth/auth-provider";
import { loginErrorKey } from "@/features/auth/login-error";
import { dashboardPath } from "@/features/auth/roles";
import { ApiError } from "@/lib/api/error";
import { startForcedTwoFactorSetup } from "@/lib/api/setup-required";
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

type SetupStep = "loading" | "scan" | "recovery";

export default function LoginPage() {
  const router = useRouter();
  const { account, login, verifyTwoFactor, confirmForcedTwoFactorSetup, status } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const t = useTranslations("auth");
  const security = useTranslations("security");
  const common = useTranslations("common");
  const localizeError = useLocalizedError();

  const [challengeToken, setChallengeToken] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [useRecoveryCode, setUseRecoveryCode] = useState(false);

  const [setupToken, setSetupToken] = useState<string | null>(null);
  const [setupStep, setSetupStep] = useState<SetupStep>("loading");
  const [otpauthUri, setOtpauthUri] = useState("");
  const [manualKey, setManualKey] = useState("");
  const [qrDataUrl, setQrDataUrl] = useState("");
  const [setupCode, setSetupCode] = useState("");
  const [recoveryCodes, setRecoveryCodes] = useState<string[]>([]);

  useEffect(() => {
    if (status === "authenticated" && account) router.replace(dashboardPath(account.role));
  }, [account, router, status]);

  useEffect(() => {
    if (!otpauthUri) return;
    let cancelled = false;
    QRCode.toDataURL(otpauthUri, { margin: 1, width: 220 })
      .then((url) => { if (!cancelled) setQrDataUrl(url); })
      .catch(() => { if (!cancelled) setQrDataUrl(""); });
    return () => { cancelled = true; };
  }, [otpauthUri]);

  function resetTwoFactorState() {
    setChallengeToken(null);
    setCode("");
    setUseRecoveryCode(false);
  }

  function resetSetupState() {
    setSetupToken(null);
    setSetupStep("loading");
    setOtpauthUri("");
    setManualKey("");
    setQrDataUrl("");
    setSetupCode("");
    setRecoveryCodes([]);
  }

  async function handleCredentialsSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    resetTwoFactorState();
    resetSetupState();
    try {
      const result = await login({ username: username.trim(), password });
      if (result.kind === "two_factor_required") {
        setChallengeToken(result.challengeToken);
        return;
      }
      if (result.kind === "two_factor_setup_required") {
        setSetupToken(result.setupToken);
        const start = await startForcedTwoFactorSetup(result.setupToken);
        setOtpauthUri(start.otpauth_uri);
        setManualKey(start.manual_key);
        setSetupStep("scan");
        return;
      }
      router.replace(dashboardPath(result.account.role));
    } catch (reason) {
      const authError = loginErrorKey(reason);
      setError(authError ? t(authError) : localizeError(reason));
      resetSetupState();
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

  async function handleSetupConfirmSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!setupToken) return;
    setError("");
    setSubmitting(true);
    try {
      const result = await confirmForcedTwoFactorSetup(setupToken, setupCode.trim());
      setRecoveryCodes(result.recoveryCodes);
      setSetupStep("recovery");
    } catch (reason) {
      const key = twoFactorErrorKey(reason);
      if (key === "codeExpired") {
        resetSetupState();
        setError(t("codeExpired"));
      } else {
        setError(key ? t(key) : localizeError(reason));
      }
    } finally {
      setSubmitting(false);
    }
  }

  function finishForcedSetup() {
    if (account) router.replace(dashboardPath(account.role));
  }

  async function copyRecoveryCodes() {
    try {
      await navigator.clipboard.writeText(recoveryCodes.join("\n"));
    } catch {
      // Clipboard access can be denied - codes remain visible for manual copy.
    }
  }

  function downloadRecoveryCodes() {
    const blob = new Blob([recoveryCodes.join("\n") + "\n"], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "gigapay-recovery-codes.txt";
    link.click();
    URL.revokeObjectURL(url);
  }

  if (setupToken) {
    return (
      <main className={styles.page}>
        <section className={styles.panel}>
          <div className={styles.preferences}><LanguageSwitcher /><ThemeSwitcher /></div>
          <div className={styles.brand}>
            <div className={styles.brandPlate}>
              <Image src="/brand/gigapay-logo-horizontal.png" alt="GigaPay" width={672} height={378} priority />
            </div>
          </div>
          <div className={styles.heading}>
            <span className={styles.eyebrow}>{t("eyebrow")}</span>
            <h1>{t("twoFactorSetupRequiredTitle")}</h1>
            <p>{t("twoFactorSetupRequiredSubtitle")}</p>
          </div>

          {setupStep === "loading" && <p className={styles.setupHint}>{common("loading")}</p>}

          {setupStep === "scan" && (
            <form className={styles.form} onSubmit={handleSetupConfirmSubmit}>
              {qrDataUrl && (
                <div className={styles.qrWrap}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={qrDataUrl} alt={security("scanQrTitle")} />
                </div>
              )}
              <div>
                <p className={styles.setupHint}>{security("manualKeyLabel")}</p>
                <div className={styles.manualKey}>{manualKey}</div>
              </div>
              <label>
                {security("enterCodeLabel")}
                <input
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={6}
                  required
                  autoFocus
                  value={setupCode}
                  onChange={(e) => { setSetupCode(e.target.value); setError(""); }}
                />
              </label>
              {error && <div className={styles.error} role="alert">{error}</div>}
              <button type="submit" disabled={submitting}>
                {submitting ? t("verifying") : security("confirmEnable")}
              </button>
            </form>
          )}

          {setupStep === "recovery" && (
            <div className={styles.form}>
              <p className={styles.setupHint}>{security("recoveryCodesWarning")}</p>
              <div className={styles.recoveryGrid}>
                {recoveryCodes.map((item) => <span key={item}>{item}</span>)}
              </div>
              <div className={styles.recoveryActions}>
                <button type="button" onClick={copyRecoveryCodes}>{security("copyAll")}</button>
                <button type="button" onClick={downloadRecoveryCodes}>{security("download")}</button>
              </div>
              <button type="button" onClick={finishForcedSetup}>{security("done")}</button>
            </div>
          )}
        </section>
        <aside className={styles.visual} aria-hidden="true">
          <div className={styles.orbit}><div className={styles.coin}>₮</div></div>
          <p>{common("loginMotto")}</p>
        </aside>
      </main>
    );
  }

  if (challengeToken) {
    return (
      <main className={styles.page}>
        <section className={styles.panel}>
          <div className={styles.preferences}><LanguageSwitcher /><ThemeSwitcher /></div>
          <div className={styles.brand}>
            <div className={styles.brandPlate}>
              <Image src="/brand/gigapay-logo-horizontal.png" alt="GigaPay" width={672} height={378} priority />
            </div>
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
          <div className={styles.brandPlate}>
            <Image src="/brand/gigapay-logo-horizontal.png" alt="GigaPay" width={672} height={378} priority />
          </div>
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
