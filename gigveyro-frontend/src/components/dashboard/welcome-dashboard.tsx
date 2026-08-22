"use client";

import { useTranslations } from "next-intl";

import { useAuth } from "@/features/auth/auth-provider";
import { useEnumLabels } from "@/features/i18n/use-enum-labels";
import type { UserRole } from "@/lib/api/types";

import styles from "./welcome-dashboard.module.css";

export function WelcomeDashboard({ role }: { role: UserRole }) {
  const t = useTranslations("dashboard");
  const labels = useEnumLabels();
  const { account } = useAuth();
  const content = role === "owner"
    ? { eyebrow: t("ownerEyebrow"), title: t("ownerTitle"), text: t("ownerSubtitle") }
    : role === "merchant"
      ? { eyebrow: t("merchantEyebrow"), title: t("merchantTitle"), text: t("merchantSubtitle") }
      : { eyebrow: t("userEyebrow"), title: t("userTitle"), text: t("userSubtitle") };

  return <section>
    <div className={styles.heading}><div><span>{content.eyebrow}</span><h1>{content.title}</h1><p>{content.text}</p></div><div className={styles.accountState}><i /> {t("accountActive")}</div></div>
    <div className={styles.grid}>
      <article className={styles.hero}><div className={styles.heroGlow} /><span>{t("welcomeBack")}</span><h2>{account?.full_name}</h2><p>{t("profileLoaded")}</p><dl><div><dt>{t("username")}</dt><dd>{account?.username}</dd></div><div><dt>{t("role")}</dt><dd>{account ? labels.role(account.role) : "—"}</dd></div></dl></article>
      <article className={styles.info}><span>{t("securityEyebrow")}</span><h3>{t("secureSession")}</h3><p>{t("secureText")}</p><div><i /> {t("backendConnected")}</div></article>
    </div>
  </section>;
}
