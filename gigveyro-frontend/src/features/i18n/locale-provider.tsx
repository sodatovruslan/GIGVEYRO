"use client";

import { NextIntlClientProvider } from "next-intl";
import { type ReactNode, useMemo, useSyncExternalStore } from "react";

import en from "@/i18n/messages/en.json";
import ru from "@/i18n/messages/ru.json";
import tg from "@/i18n/messages/tg.json";

export type AppLocale = "ru" | "en" | "tg";
const catalogs = { ru, en, tg } as const;
const intlLocales: Record<AppLocale, string> = { ru: "ru-RU", en: "en-US", tg: "tg-TJ" };
const listeners = new Set<() => void>();

function getSnapshot(): AppLocale {
  if (typeof document === "undefined") return "ru";
  const locale = document.documentElement.dataset.locale;
  return locale === "en" || locale === "tg" ? locale : "ru";
}
function subscribe(listener: () => void) { listeners.add(listener); return () => listeners.delete(listener); }

export function setAppLocale(locale: AppLocale) {
  localStorage.setItem("gigveyro-locale", locale);
  document.documentElement.dataset.locale = locale;
  document.documentElement.lang = intlLocales[locale];
  listeners.forEach((listener) => listener());
}

export function LocaleProvider({ children }: { children: ReactNode }) {
  const locale = useSyncExternalStore<AppLocale>(subscribe, getSnapshot, () => "ru");
  const messages = useMemo(() => catalogs[locale], [locale]);
  return <NextIntlClientProvider key={locale} locale={intlLocales[locale]} messages={messages} timeZone="Europe/Moscow">{children}</NextIntlClientProvider>;
}

export function useAppLocale() {
  return useSyncExternalStore<AppLocale>(subscribe, getSnapshot, () => "ru");
}
