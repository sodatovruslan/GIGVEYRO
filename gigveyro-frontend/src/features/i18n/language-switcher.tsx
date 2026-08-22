"use client";

import { useTranslations } from "next-intl";

import { type AppLocale, setAppLocale, useAppLocale } from "./locale-provider";
import styles from "./language-switcher.module.css";

export function LanguageSwitcher({ className = "" }: { className?: string }) {
  const locale = useAppLocale();
  const t = useTranslations("language");
  return <select className={`${styles.switcher} ${className}`} aria-label={t("label")} title={t("label")} value={locale} onChange={(event) => setAppLocale(event.target.value as AppLocale)}>
    <option value="ru">RU · {t("ru")}</option><option value="en">EN · {t("en")}</option><option value="tg">TG · {t("tg")}</option>
  </select>;
}
