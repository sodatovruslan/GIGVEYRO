"use client";

import { createContext, type ReactNode, useContext, useEffect, useMemo, useSyncExternalStore } from "react";

export type ThemePreference = "dark" | "light" | "system";

interface ThemeContextValue { theme: ThemePreference; setTheme: (theme: ThemePreference) => void }
const ThemeContext = createContext<ThemeContextValue | null>(null);
const listeners = new Set<() => void>();

function getSnapshot(): ThemePreference {
  if (typeof document === "undefined") return "system";
  const value = document.documentElement.dataset.themePreference;
  return value === "dark" || value === "light" ? value : "system";
}
function subscribe(listener: () => void) { listeners.add(listener); return () => listeners.delete(listener); }
function applyTheme(preference: ThemePreference) {
  const resolved = preference === "system"
    ? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
    : preference;
  document.documentElement.dataset.theme = resolved;
  document.documentElement.dataset.themePreference = preference;
  document.documentElement.style.colorScheme = resolved;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const theme = useSyncExternalStore<ThemePreference>(subscribe, getSnapshot, () => "system");
  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const updateSystemTheme = () => { if (getSnapshot() === "system") applyTheme("system"); };
    media.addEventListener("change", updateSystemTheme);
    document.documentElement.classList.add("theme-ready");
    return () => media.removeEventListener("change", updateSystemTheme);
  }, []);
  const value = useMemo<ThemeContextValue>(() => ({ theme, setTheme: (next: ThemePreference) => {
    localStorage.setItem("gigveyro-theme", next);
    applyTheme(next);
    listeners.forEach((listener) => listener());
  } }), [theme]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) throw new Error("useTheme must be used inside ThemeProvider");
  return context;
}
