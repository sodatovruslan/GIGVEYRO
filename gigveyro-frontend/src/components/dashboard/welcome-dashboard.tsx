"use client";

import { useAuth } from "@/features/auth/auth-provider";
import type { UserRole } from "@/lib/api/types";

import styles from "./welcome-dashboard.module.css";

const copy: Record<UserRole, { eyebrow: string; title: string; text: string }> = {
  owner: { eyebrow: "OWNER CONTROL CENTER", title: "Панель управления", text: "Управляйте аккаунтами, финансовыми операциями и состоянием платформы." },
  user: { eyebrow: "PERSONAL WORKSPACE", title: "Главная", text: "Ваш защищённый кабинет для работы с балансом, реквизитами и сделками." },
  merchant: { eyebrow: "MERCHANT WORKSPACE", title: "Кабинет мерчанта", text: "Создавайте сделки и контролируйте расчёты с платформой." },
};

export function WelcomeDashboard({ role }: { role: UserRole }) {
  const { account } = useAuth();
  const content = copy[role];
  return (
    <section>
      <div className={styles.heading}>
        <div><span>{content.eyebrow}</span><h1>{content.title}</h1><p>{content.text}</p></div>
        <div className={styles.accountState}><i /> Аккаунт активен</div>
      </div>
      <div className={styles.grid}>
        <article className={styles.hero}>
          <div className={styles.heroGlow} />
          <span>ДОБРО ПОЖАЛОВАТЬ</span>
          <h2>{account?.full_name}</h2>
          <p>Данные профиля получены из Backend V1 через защищённую сессию.</p>
          <dl><div><dt>Логин</dt><dd>{account?.username}</dd></div><div><dt>Роль</dt><dd>{account?.role}</dd></div></dl>
        </article>
        <article className={styles.info}>
          <span>SECURITY</span><h3>Защищённая сессия</h3>
          <p>Токены хранятся в HttpOnly cookies и автоматически обновляются через FastAPI.</p>
          <div><i /> Backend connected</div>
        </article>
      </div>
    </section>
  );
}
