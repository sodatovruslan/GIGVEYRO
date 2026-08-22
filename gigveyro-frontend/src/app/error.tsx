"use client";

import { useTranslations } from "next-intl";

import styles from "./status-page.module.css";

export default function ErrorPage({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const t = useTranslations("errors"); const common = useTranslations("common");
  return <main className={styles.page}><section className={styles.card}><div className={styles.mark}>!</div><h1>{t("pageTitle")}</h1><p>{t("pageText")}</p><button onClick={reset}>{common("retry")}</button></section></main>;
}
