import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AuthProvider } from "@/features/auth/auth-provider";
import { ThemeProvider } from "@/features/theme/theme-provider";

import "./globals.css";

export const metadata: Metadata = {
  title: { default: "GIGVEYRO", template: "%s | GIGVEYRO" },
  description: "GIGVEYRO USDT payment gateway",
};

const themeBootstrap = `(function(){try{var p=localStorage.getItem('gigveyro-theme');if(p!=='dark'&&p!=='light'&&p!=='system')p='system';var r=p==='system'?(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'):p;var e=document.documentElement;e.dataset.theme=r;e.dataset.themePreference=p;e.style.colorScheme=r}catch(e){document.documentElement.dataset.theme='dark';document.documentElement.dataset.themePreference='system'}})()`;

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ru" suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{ __html: themeBootstrap }} /></head>
      <body>
        <ThemeProvider><AuthProvider>{children}</AuthProvider></ThemeProvider>
      </body>
    </html>
  );
}
