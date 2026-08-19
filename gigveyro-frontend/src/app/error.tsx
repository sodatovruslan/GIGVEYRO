"use client";

import styles from "./status-page.module.css";

export default function ErrorPage({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return <main className={styles.page}><section className={styles.card}><div className={styles.mark}>!</div><h1>Что-то пошло не так</h1><p>Интерфейс не смог загрузить этот экран. Данные на backend не изменены.</p><button onClick={reset}>Повторить</button></section></main>;
}
