"use client";

import { useAppFormat } from "@/features/i18n/use-app-format";

import styles from "./user.module.css";

export function PageHeading({ eyebrow, title, text }: { eyebrow: string; title: string; text: string }) {
  return <div className={styles.pageHeading}><span>{eyebrow}</span><h1>{title}</h1><p>{text}</p></div>;
}

export function BalanceCard({ label, value, loading, accent = false }: { label: string; value?: string; loading: boolean; accent?: boolean }) {
  const format = useAppFormat();
  return <article className={styles.balanceCard}><span>{label}</span><div><strong className={accent ? styles.accent : ""}>{loading ? "—" : format.number(value || 0)}</strong><small>USDT</small></div></article>;
}
