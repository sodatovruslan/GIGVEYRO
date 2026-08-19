import styles from "./user.module.css";

export function PageHeading({ eyebrow, title, text }: { eyebrow: string; title: string; text: string }) {
  return <div className={styles.pageHeading}><span>{eyebrow}</span><h1>{title}</h1><p>{text}</p></div>;
}

export function BalanceCard({ label, value, loading, accent = false }: { label: string; value?: string; loading: boolean; accent?: boolean }) {
  return <article className={styles.balanceCard}><span>{label}</span><div><strong className={accent ? styles.accent : ""}>{loading ? "—" : value || "0.00000000"}</strong><small>USDT</small></div></article>;
}
