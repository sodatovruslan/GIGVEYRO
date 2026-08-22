"use client";

import { type FormEvent, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import QRCode from "qrcode";

import { useAppFormat } from "@/features/i18n/use-app-format";
import { useLocalizedError } from "@/features/i18n/use-localized-error";
import { securityApi } from "@/lib/api/security";
import { useApiQuery } from "@/lib/hooks/use-api-query";

import styles from "./settings.module.css";

type Dialog = "enable" | "disable" | "regenerate" | null;
type EnableStep = "password" | "scan" | "recovery";

export default function OwnerSettingsPage() {
  const t = useTranslations("security");
  const common = useTranslations("common");
  const format = useAppFormat();
  const localizeError = useLocalizedError();

  const statusQuery = useApiQuery(() => securityApi.status(), "two-factor-status");

  const [dialog, setDialog] = useState<Dialog>(null);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");
  const [successMessage, setSuccessMessage] = useState("");

  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [enableStep, setEnableStep] = useState<EnableStep>("password");
  const [otpauthUri, setOtpauthUri] = useState("");
  const [manualKey, setManualKey] = useState("");
  const [qrDataUrl, setQrDataUrl] = useState("");
  const [recoveryCodes, setRecoveryCodes] = useState<string[]>([]);

  useEffect(() => {
    if (!successMessage) return;
    const timeout = window.setTimeout(() => setSuccessMessage(""), 3500);
    return () => window.clearTimeout(timeout);
  }, [successMessage]);

  useEffect(() => {
    if (!otpauthUri) return;
    let cancelled = false;
    QRCode.toDataURL(otpauthUri, { margin: 1, width: 240 })
      .then((url) => { if (!cancelled) setQrDataUrl(url); })
      .catch(() => { if (!cancelled) setQrDataUrl(""); });
    return () => { cancelled = true; };
  }, [otpauthUri]);

  function openDialog(next: Dialog) {
    setFormError("");
    setPassword("");
    setCode("");
    setEnableStep("password");
    setOtpauthUri("");
    setManualKey("");
    setQrDataUrl("");
    setRecoveryCodes([]);
    setDialog(next);
  }

  function closeDialog() {
    setDialog(null);
    setOtpauthUri("");
    setQrDataUrl("");
  }

  async function submitEnablePassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setFormError("");
    try {
      const result = await securityApi.setupStart(password);
      setOtpauthUri(result.otpauth_uri);
      setManualKey(result.manual_key);
      setEnableStep("scan");
      setCode("");
    } catch (reason) {
      setFormError(localizeError(reason));
    } finally {
      setSaving(false);
    }
  }

  async function submitEnableCode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setFormError("");
    try {
      const result = await securityApi.setupConfirm(code);
      setRecoveryCodes(result.recovery_codes);
      setEnableStep("recovery");
    } catch (reason) {
      setFormError(localizeError(reason));
    } finally {
      setSaving(false);
    }
  }

  async function submitDisable(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setFormError("");
    try {
      await securityApi.disable(password, code);
      closeDialog();
      setSuccessMessage(t("disableSuccess"));
      await statusQuery.refetch();
    } catch (reason) {
      setFormError(localizeError(reason));
    } finally {
      setSaving(false);
    }
  }

  async function submitRegenerate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setFormError("");
    try {
      const result = await securityApi.regenerateRecoveryCodes(password, code);
      setRecoveryCodes(result.recovery_codes);
    } catch (reason) {
      setFormError(localizeError(reason));
    } finally {
      setSaving(false);
    }
  }

  function finishEnable() {
    closeDialog();
    setSuccessMessage(t("enableSuccess"));
    void statusQuery.refetch();
  }

  async function copyRecoveryCodes() {
    try {
      await navigator.clipboard.writeText(recoveryCodes.join("\n"));
    } catch {
      // Clipboard access can be denied by the browser - non-fatal, the
      // codes are still visible on screen for manual copying.
    }
  }

  function downloadRecoveryCodes() {
    const blob = new Blob([recoveryCodes.join("\n") + "\n"], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "gigveyro-recovery-codes.txt";
    link.click();
    URL.revokeObjectURL(url);
  }

  const status = statusQuery.data;

  return (
    <section className={styles.page}>
      {successMessage && <div className={styles.toast} role="status" aria-live="polite">{successMessage}</div>}
      <div className={styles.header}><h1>{t("title")}</h1></div>

      <div className={styles.card}>
        <div className={styles.cardHeader}>
          <div>
            <h2>{t("twoFactorTitle")}</h2>
            <p>{t("twoFactorDescription")}</p>
          </div>
        </div>

        {statusQuery.loading ? (
          <p className={styles.meta}>{common("loading")}</p>
        ) : statusQuery.error ? (
          <p className={styles.formError}>{statusQuery.error}</p>
        ) : (
          <>
            <div className={styles.statusRow}>
              <span className={`${styles.statusBadge} ${status?.enabled ? styles.statusEnabled : styles.statusDisabled}`}>
                {status?.enabled ? t("statusEnabled") : t("statusDisabled")}
              </span>
              {status?.enabled && status.enabled_at && (
                <span className={styles.meta}>{t("enabledSince", { date: format.date(status.enabled_at) })}</span>
              )}
            </div>
            {status?.enabled && (
              <p className={styles.meta}>{t("recoveryCodesRemaining", { count: status.recovery_codes_remaining })}</p>
            )}
            <div className={styles.actions}>
              {status?.enabled ? (
                <>
                  <button className={styles.secondaryButton} onClick={() => openDialog("regenerate")}>
                    {t("regenerateCodes")}
                  </button>
                  <button className={styles.dangerButton} onClick={() => openDialog("disable")}>
                    {t("disable")}
                  </button>
                </>
              ) : (
                <button className={styles.primaryButton} onClick={() => openDialog("enable")}>
                  {t("enable")}
                </button>
              )}
            </div>
          </>
        )}
      </div>

      {dialog === "enable" && (
        <div className={styles.modalBackdrop} onMouseDown={closeDialog}>
          <div className={styles.modal} onMouseDown={(event) => event.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h2>{t("twoFactorTitle")}</h2>
              <button onClick={closeDialog} aria-label={common("cancel")}>×</button>
            </div>

            {enableStep === "password" && (
              <form className={styles.form} onSubmit={submitEnablePassword}>
                <label>
                  {t("currentPasswordLabel")}
                  <input
                    type="password"
                    autoComplete="current-password"
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                  />
                </label>
                {formError && <div className={styles.formError}>{formError}</div>}
                <div className={styles.formActions}>
                  <button type="button" className={styles.secondaryButton} onClick={closeDialog}>{common("cancel")}</button>
                  <button type="submit" className={styles.primaryButton} disabled={saving}>
                    {saving ? common("saving") : t("continueButton")}
                  </button>
                </div>
              </form>
            )}

            {enableStep === "scan" && (
              <form className={styles.form} onSubmit={submitEnableCode}>
                <p>{t("scanQrTitle")}</p>
                <p className={styles.meta}>{t("scanQrDescription")}</p>
                <div className={styles.qrWrap}>
                  {qrDataUrl && <img src={qrDataUrl} alt={t("scanQrTitle")} />}
                </div>
                <div>
                  <p className={styles.meta}>{t("manualKeyLabel")}</p>
                  <div className={styles.manualKey}>{manualKey}</div>
                </div>
                <label>
                  {t("enterCodeLabel")}
                  <input
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    maxLength={6}
                    required
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                  />
                </label>
                {formError && <div className={styles.formError}>{formError}</div>}
                <div className={styles.formActions}>
                  <button type="button" className={styles.secondaryButton} onClick={closeDialog}>{common("cancel")}</button>
                  <button type="submit" className={styles.primaryButton} disabled={saving}>
                    {saving ? common("saving") : t("confirmEnable")}
                  </button>
                </div>
              </form>
            )}

            {enableStep === "recovery" && (
              <div className={styles.form}>
                <h2>{t("recoveryCodesTitle")}</h2>
                <div className={styles.recoveryWarning}>{t("recoveryCodesWarning")}</div>
                <div className={styles.recoveryGrid}>
                  {recoveryCodes.map((item) => <span key={item}>{item}</span>)}
                </div>
                <div className={styles.formActions}>
                  <button type="button" className={styles.secondaryButton} onClick={copyRecoveryCodes}>{t("copyAll")}</button>
                  <button type="button" className={styles.secondaryButton} onClick={downloadRecoveryCodes}>{t("download")}</button>
                  <button type="button" className={styles.primaryButton} onClick={finishEnable}>{t("done")}</button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {dialog === "disable" && (
        <div className={styles.modalBackdrop} onMouseDown={closeDialog}>
          <div className={styles.modal} onMouseDown={(event) => event.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h2>{t("disableTitle")}</h2>
              <button onClick={closeDialog} aria-label={common("cancel")}>×</button>
            </div>
            <p className={styles.meta}>{t("disableWarning")}</p>
            <form className={styles.form} onSubmit={submitDisable}>
              <label>
                {t("currentPasswordLabel")}
                <input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
              </label>
              <label>
                {t("codeLabel")}
                <input autoComplete="one-time-code" required value={code} onChange={(e) => setCode(e.target.value)} />
              </label>
              {formError && <div className={styles.formError}>{formError}</div>}
              <div className={styles.formActions}>
                <button type="button" className={styles.secondaryButton} onClick={closeDialog}>{common("cancel")}</button>
                <button type="submit" className={styles.dangerButton} disabled={saving}>
                  {saving ? common("saving") : t("disable")}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {dialog === "regenerate" && (
        <div className={styles.modalBackdrop} onMouseDown={closeDialog}>
          <div className={styles.modal} onMouseDown={(event) => event.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h2>{t("regenerateTitle")}</h2>
              <button onClick={closeDialog} aria-label={common("cancel")}>×</button>
            </div>
            {recoveryCodes.length === 0 ? (
              <>
                <p className={styles.meta}>{t("regenerateWarning")}</p>
                <form className={styles.form} onSubmit={submitRegenerate}>
                  <label>
                    {t("currentPasswordLabel")}
                    <input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
                  </label>
                  <label>
                    {t("enterCodeLabel")}
                    <input inputMode="numeric" autoComplete="one-time-code" maxLength={6} required value={code} onChange={(e) => setCode(e.target.value)} />
                  </label>
                  {formError && <div className={styles.formError}>{formError}</div>}
                  <div className={styles.formActions}>
                    <button type="button" className={styles.secondaryButton} onClick={closeDialog}>{common("cancel")}</button>
                    <button type="submit" className={styles.primaryButton} disabled={saving}>
                      {saving ? common("saving") : t("regenerateCodes")}
                    </button>
                  </div>
                </form>
              </>
            ) : (
              <div className={styles.form}>
                <div className={styles.recoveryWarning}>{t("recoveryCodesWarning")}</div>
                <div className={styles.recoveryGrid}>
                  {recoveryCodes.map((item) => <span key={item}>{item}</span>)}
                </div>
                <div className={styles.formActions}>
                  <button type="button" className={styles.secondaryButton} onClick={copyRecoveryCodes}>{t("copyAll")}</button>
                  <button type="button" className={styles.secondaryButton} onClick={downloadRecoveryCodes}>{t("download")}</button>
                  <button
                    type="button"
                    className={styles.primaryButton}
                    onClick={() => { closeDialog(); setSuccessMessage(t("regenerateSuccess")); }}
                  >
                    {t("done")}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
