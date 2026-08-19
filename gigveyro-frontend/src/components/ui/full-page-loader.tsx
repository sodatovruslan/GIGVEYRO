import styles from "./full-page-loader.module.css";

export function FullPageLoader({ label = "Загрузка" }: { label?: string }) {
  return (
    <main className={styles.page} aria-live="polite" aria-busy="true">
      <div className={styles.mark}>G</div>
      <div className={styles.spinner} />
      <p>{label}</p>
    </main>
  );
}
