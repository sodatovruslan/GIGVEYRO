"use client";

import { useTranslations } from "next-intl";
import styles from "./full-page-loader.module.css";

export function FullPageLoader({ label }: { label?: string }) {
  const t = useTranslations("common");
  return (
    <main className={styles.page} aria-live="polite" aria-busy="true">
      <div className={styles.mark}>G</div>
      <div className={styles.spinner} />
      <p>{label || t("loading")}</p>
    </main>
  );
}
