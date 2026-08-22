"use client";
import Link from "next/link";
import { useTranslations } from "next-intl";

import styles from "./status-page.module.css";

export default function NotFoundPage() { const t=useTranslations("errors"); return <main className={styles.page}><section className={styles.card}><div className={styles.mark}>G</div><h1>{t("notFoundTitle")}</h1><p>{t("notFoundText")}</p><Link href="/">{t("home")}</Link></section></main>; }
