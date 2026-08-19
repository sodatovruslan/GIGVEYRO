"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { type ReactNode, useState } from "react";

import { useAuth } from "@/features/auth/auth-provider";
import type { UserRole } from "@/lib/api/types";

import styles from "./dashboard-shell.module.css";

interface NavigationItem { href: string; label: string; glyph: string }

const navigation: Record<UserRole, NavigationItem[]> = {
  owner: [
    { href: "/owner", label: "Обзор", glyph: "◇" },
    { href: "/owner/accounts", label: "Аккаунты", glyph: "◎" },
    { href: "/owner/deals", label: "Сделки", glyph: "⇄" },
    { href: "/owner/deposits", label: "Депозиты", glyph: "↓" },
    { href: "/owner/withdrawals", label: "Выводы", glyph: "↗" },
    { href: "/owner/appeals", label: "Апелляции", glyph: "!" },
    { href: "/owner/notifications", label: "Уведомления", glyph: "○" },
    { href: "/owner/analytics", label: "Аналитика", glyph: "⌁" },
    { href: "/owner/integrations", label: "Интеграции", glyph: "⌘" },
    { href: "/owner/audit", label: "Журнал", glyph: "≡" },
  ],
  user: [
    { href: "/user", label: "Главная", glyph: "◇" },
    { href: "/user/wallet", label: "Баланс", glyph: "₮" },
    { href: "/user/deposits", label: "Пополнение", glyph: "↓" },
    { href: "/user/requisites", label: "Реквизиты", glyph: "▣" },
    { href: "/user/deals", label: "Сделки", glyph: "⇄" },
    { href: "/user/appeals", label: "Апелляции", glyph: "!" },
    { href: "/user/notifications", label: "Уведомления", glyph: "○" },
  ],
  merchant: [
    { href: "/merchant", label: "Главная", glyph: "◇" },
    { href: "/merchant/wallet", label: "Баланс", glyph: "₮" },
    { href: "/merchant/deals", label: "Сделки", glyph: "⇄" },
    { href: "/merchant/withdrawals", label: "Выводы", glyph: "↗" },
    { href: "/merchant/appeals", label: "Апелляции", glyph: "!" },
    { href: "/merchant/notifications", label: "Уведомления", glyph: "○" },
  ],
};

const roleLabels: Record<UserRole, string> = { owner: "Владелец", user: "Пользователь", merchant: "Мерчант" };

export function DashboardShell({ role, children }: { role: UserRole; children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { account, logout } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);

  async function handleLogout() {
    await logout();
    router.replace("/login");
  }

  return (
    <div className={styles.shell}>
      {menuOpen && <button className={styles.backdrop} aria-label="Закрыть меню" onClick={() => setMenuOpen(false)} />}
      <aside className={`${styles.sidebar} ${menuOpen ? styles.open : ""}`}>
        <Link href={`/${role}`} className={styles.brand} onClick={() => setMenuOpen(false)}>
          <span className={styles.logo}>G</span>
          <span><strong>GIGVEYRO</strong><small>PAYMENT GATEWAY</small></span>
        </Link>
        <nav className={styles.nav} aria-label="Основная навигация">
          <p>РАБОЧЕЕ ПРОСТРАНСТВО</p>
          {navigation[role].map((item) => {
            const active = pathname === item.href || (item.href !== `/${role}` && pathname.startsWith(`${item.href}/`));
            return (
              <Link key={item.href} href={item.href} className={active ? styles.active : ""} onClick={() => setMenuOpen(false)}>
                <span className={styles.glyph}>{item.glyph}</span>{item.label}
              </Link>
            );
          })}
        </nav>
        <div className={styles.profile}>
          <div className={styles.avatar}>{account?.full_name?.slice(0, 1).toUpperCase()}</div>
          <div><strong>{account?.full_name}</strong><span>{roleLabels[role]}</span></div>
          <button onClick={handleLogout} title="Выйти" aria-label="Выйти">↪</button>
        </div>
      </aside>
      <div className={styles.workspace}>
        <header className={styles.header}>
          <button className={styles.menuButton} onClick={() => setMenuOpen(true)} aria-label="Открыть меню">☰</button>
          <div><span className={styles.liveDot} /> Система работает штатно</div>
          <div className={styles.headerUser}><span>{account?.username}</span><div>{account?.full_name?.slice(0, 1).toUpperCase()}</div></div>
        </header>
        <main className={styles.content}>{children}</main>
      </div>
    </div>
  );
}
