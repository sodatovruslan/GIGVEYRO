"use client";

import { type ThemePreference, useTheme } from "./theme-provider";
import styles from "./theme-switcher.module.css";

const options: Array<{ value: ThemePreference; icon: string; label: string }> = [
  { value: "light", icon: "☀", label: "Светлая тема" },
  { value: "dark", icon: "☾", label: "Тёмная тема" },
  { value: "system", icon: "◐", label: "Системная тема" },
];

export function ThemeSwitcher({ className = "" }: { className?: string }) {
  const { theme, setTheme } = useTheme();
  return <div className={`${styles.switcher} ${className}`} role="group" aria-label="Выбор темы">
    {options.map((option) => <button key={option.value} type="button" className={theme === option.value ? styles.active : ""} aria-label={option.label} title={option.label} aria-pressed={theme === option.value} onClick={() => setTheme(option.value)}>{option.icon}</button>)}
  </div>;
}
