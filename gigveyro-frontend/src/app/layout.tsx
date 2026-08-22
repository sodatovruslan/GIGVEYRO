import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AuthProvider } from "@/features/auth/auth-provider";
import { ThemeProvider } from "@/features/theme/theme-provider";
import { LocaleProvider } from "@/features/i18n/locale-provider";
import { RealtimeProvider } from "@/features/realtime/realtime-provider";

import "./globals.css";

export const metadata: Metadata = {
  title: { default: "GIGVEYRO", template: "%s | GIGVEYRO" },
  description: "GIGVEYRO USDT payment gateway",
};

const themeBootstrap = `(function(){try{var p=localStorage.getItem('gigveyro-theme');if(p!=='dark'&&p!=='light'&&p!=='system')p='system';var r=p==='system'?(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'):p;var e=document.documentElement;e.dataset.theme=r;e.dataset.themePreference=p;e.style.colorScheme=r}catch(e){document.documentElement.dataset.theme='dark';document.documentElement.dataset.themePreference='system'}})()`;
const localeBootstrap = `(function(){try{var l=localStorage.getItem('gigveyro-locale');if(l!=='en'&&l!=='tg')l='ru';var e=document.documentElement;e.dataset.locale=l;e.lang=l==='en'?'en-US':l==='tg'?'tg-TJ':'ru-RU'}catch(e){document.documentElement.dataset.locale='ru'}})()`;

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ru" suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{ __html: `${themeBootstrap};${localeBootstrap}` }} /></head>
      <body>
        <LocaleProvider><ThemeProvider><AuthProvider><RealtimeProvider>{children}</RealtimeProvider></AuthProvider></ThemeProvider></LocaleProvider>
      </body>
    </html>
  );
}
