"use client";

import { type FormEvent, useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { useLocalizedError } from "@/features/i18n/use-localized-error";
import { merchantApi } from "@/lib/api/merchant";
import { useApiQuery } from "@/lib/hooks/use-api-query";

import styles from "../../app/user/user.module.css";

export function StoreSettingsPanel() {
  const t = useTranslations("storeSettings");
  const localizeError = useLocalizedError();
  const query = useApiQuery(merchantApi.profile, "merchant-profile");

  const [storeName, setStoreName] = useState("");
  const [description, setDescription] = useState("");
  const [supportContact, setSupportContact] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!query.data) return;
    const data = query.data;
    const timeout = window.setTimeout(() => {
      setStoreName(data.store_name || "");
      setDescription(data.description || "");
      setSupportContact(data.support_contact || "");
    }, 0);
    return () => window.clearTimeout(timeout);
  }, [query.data]);

  async function save(event: FormEvent) {
    event.preventDefault(); setSaving(true); setError(""); setSaved(false);
    try {
      await merchantApi.updateProfile({
        store_name: storeName || null,
        description: description || null,
        support_contact: supportContact || null,
      });
      setSaved(true);
    } catch (reason) { setError(localizeError(reason)); }
    finally { setSaving(false); }
  }

  if (query.loading) return <div className={styles.state}>{t("loading")}</div>;

  return <div className={styles.contentCard} style={{ marginTop: 24 }}>
    <div className={styles.contentHeader}><h2>{t("title")}</h2></div>
    <p>{t("subtitle")}</p>
    <form className={styles.form} onSubmit={save}>
      <label>{t("storeName")}<input maxLength={255} value={storeName} onChange={(event) => setStoreName(event.target.value)} /></label>
      <label>{t("description")}<input maxLength={2000} value={description} onChange={(event) => setDescription(event.target.value)} /></label>
      <label>{t("supportContact")}<input maxLength={255} value={supportContact} onChange={(event) => setSupportContact(event.target.value)} /></label>
      {error && <div className={styles.formError}>{error}</div>}
      <div className={styles.formActions}><button disabled={saving}>{saved ? t("saved") : t("save")}</button></div>
    </form>
  </div>;
}
