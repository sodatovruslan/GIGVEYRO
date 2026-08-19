import Link from "next/link";

import styles from "./status-page.module.css";

export default function NotFoundPage() { return <main className={styles.page}><section className={styles.card}><div className={styles.mark}>G</div><h1>Страница не найдена</h1><p>Проверьте адрес или вернитесь в рабочее пространство.</p><Link href="/">На главную</Link></section></main>; }
