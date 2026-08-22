"use client";

import { type ThemePreference, useTheme } from "./theme-provider";
import { useTranslations } from "next-intl";
import styles from "./theme-switcher.module.css";

const options: Array<{ value: ThemePreference; icon: string; label: "light" | "dark" | "system" }> = [
  { value: "light", icon: "☀", label: "light" },
  { value: "dark", icon: "☾", label: "dark" },
  { value: "system", icon: "◐", label: "system" },
];

export function ThemeSwitcher({ className = "" }: { className?: string }) {
  const { theme, setTheme } = useTheme();
  const t = useTranslations("theme");
  return <div className={`${styles.switcher} ${className}`} role="group" aria-label={t("label")}>
    {options.map((option) => <button key={option.value} type="button" className={theme === option.value ? styles.active : ""} aria-label={t(option.label)} title={t(option.label)} aria-pressed={theme === option.value} onClick={() => setTheme(option.value)}>{option.icon}</button>)}
  </div>;
}
