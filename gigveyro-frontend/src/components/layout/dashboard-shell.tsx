"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { type ReactNode, useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { useAuth } from "@/features/auth/auth-provider";
import { notificationsApi } from "@/lib/api/notifications";
import type { UserRole } from "@/lib/api/types";
import { ThemeSwitcher } from "@/features/theme/theme-switcher";
import { LanguageSwitcher } from "@/features/i18n/language-switcher";

import styles from "./dashboard-shell.module.css";

type NavigationKey = "overview"|"home"|"accounts"|"deals"|"deposits"|"funding"|"withdrawals"|"appeals"|"notifications"|"analytics"|"integrations"|"audit"|"wallet"|"requisites";
interface NavigationItem { href: string; label: NavigationKey; glyph: string }

const navigation: Record<UserRole, NavigationItem[]> = {
  owner: [
    { href: "/owner", label: "overview", glyph: "◇" }, { href: "/owner/accounts", label: "accounts", glyph: "◎" }, { href: "/owner/deals", label: "deals", glyph: "⇄" }, { href: "/owner/deposits", label: "deposits", glyph: "↓" }, { href: "/owner/withdrawals", label: "withdrawals", glyph: "↗" }, { href: "/owner/appeals", label: "appeals", glyph: "!" }, { href: "/owner/notifications", label: "notifications", glyph: "○" }, { href: "/owner/analytics", label: "analytics", glyph: "⌁" }, { href: "/owner/integrations", label: "integrations", glyph: "⌘" }, { href: "/owner/audit", label: "audit", glyph: "≡" },
  ],
  user: [
    { href: "/user", label: "home", glyph: "◇" }, { href: "/user/wallet", label: "wallet", glyph: "₮" }, { href: "/user/deposits", label: "funding", glyph: "↓" }, { href: "/user/requisites", label: "requisites", glyph: "▣" }, { href: "/user/deals", label: "deals", glyph: "⇄" }, { href: "/user/appeals", label: "appeals", glyph: "!" }, { href: "/user/notifications", label: "notifications", glyph: "○" },
  ],
  merchant: [
    { href: "/merchant", label: "home", glyph: "◇" }, { href: "/merchant/wallet", label: "wallet", glyph: "₮" }, { href: "/merchant/deals", label: "deals", glyph: "⇄" }, { href: "/merchant/withdrawals", label: "withdrawals", glyph: "↗" }, { href: "/merchant/appeals", label: "appeals", glyph: "!" }, { href: "/merchant/notifications", label: "notifications", glyph: "○" },
  ],
};

export function DashboardShell({ role, children }: { role: UserRole; children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { account, logout } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const t = useTranslations("navigation"); const tRoles = useTranslations("roles"); const tHeader = useTranslations("header"); const common = useTranslations("common");

  useEffect(() => {
    let active = true;
    function refresh() { notificationsApi.unreadCount().then((result) => { if (active) setUnreadCount(result.unread_count); }).catch(() => {}); }
    refresh();
    window.addEventListener("gigveyro:notifications-updated", refresh);
    return () => { active = false; window.removeEventListener("gigveyro:notifications-updated", refresh); };
  }, [pathname]);

  async function handleLogout() {
    await logout();
    router.replace("/login");
  }

  return (
    <div className={styles.shell}>
      {menuOpen && <button className={styles.backdrop} aria-label={t("closeMenu")} onClick={() => setMenuOpen(false)} />}
      <aside className={`${styles.sidebar} ${menuOpen ? styles.open : ""}`}>
        <Link href={`/${role}`} className={styles.brand} onClick={() => setMenuOpen(false)}>
          <span className={styles.logo}>G</span>
          <span><strong>GIGVEYRO</strong><small>{common("paymentGateway")}</small></span>
        </Link>
        <nav className={styles.nav} aria-label={t("workspace")}>
          <p>{t("workspace")}</p>
          {navigation[role].map((item) => {
            const active = pathname === item.href || (item.href !== `/${role}` && pathname.startsWith(`${item.href}/`));
            return (
              <Link key={item.href} href={item.href} className={active ? styles.active : ""} onClick={() => setMenuOpen(false)}>
                <span className={styles.glyph}>{item.glyph}</span>{t(item.label)}
                {item.label === "notifications" && unreadCount > 0 && <span className={styles.badge}>{unreadCount > 99 ? "99+" : unreadCount}</span>}
              </Link>
            );
          })}
        </nav>
        <div className={styles.profile}>
          <div className={styles.avatar}>{account?.full_name?.slice(0, 1).toUpperCase()}</div>
          <div><strong>{account?.full_name}</strong><span>{tRoles(role)}</span></div>
          <button onClick={handleLogout} title={t("logout")} aria-label={t("logout")}>↪</button>
        </div>
      </aside>
      <div className={styles.workspace}>
        <header className={styles.header}>
          <button className={styles.menuButton} onClick={() => setMenuOpen(true)} aria-label={t("openMenu")}>☰</button>
          <div><span className={styles.liveDot} /> {tHeader("healthy")}</div>
          <div className={styles.headerActions}><LanguageSwitcher /><ThemeSwitcher /><div className={styles.headerUser}><span>{account?.username}</span><div>{account?.full_name?.slice(0, 1).toUpperCase()}</div></div></div>
        </header>
        <main className={styles.content}>{children}</main>
      </div>
    </div>
  );
}
