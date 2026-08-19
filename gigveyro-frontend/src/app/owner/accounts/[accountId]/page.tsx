"use client";

import Link from "next/link";
import { type FormEvent, useState } from "react";
import { useParams } from "next/navigation";

import { ApiError } from "@/lib/api/error";
import { ownerAccountsApi } from "@/lib/api/owner-accounts";
import type { MerchantWallet, Wallet } from "@/lib/api/types";
import { useApiQuery } from "@/lib/hooks/use-api-query";

import styles from "./account.module.css";

type Dialog = "edit" | "password" | "allocate" | "insurance" | "adjust" | null;

export default function OwnerAccountDetailsPage() {
  const accountId = useParams<{ accountId: string }>().accountId;
  const [dialog, setDialog] = useState<Dialog>(null);
  const [mutationError, setMutationError] = useState("");
  const [saving, setSaving] = useState(false);
  const [password, setPassword] = useState("");
  const [amount, setAmount] = useState("");
  const [description, setDescription] = useState("");
  const accountQuery = useApiQuery(() => ownerAccountsApi.get(accountId), `account:${accountId}`);
  const account = accountQuery.data;
  const walletQuery = useApiQuery<Wallet | MerchantWallet>(
    () => account?.role === "merchant" ? ownerAccountsApi.merchantWallet(accountId) : ownerAccountsApi.userWallet(accountId),
    `wallet:${accountId}:${account?.role || "unknown"}`,
  );
  const ledgerQuery = useApiQuery(
    () => ownerAccountsApi.ledger(accountId, account?.role === "merchant"),
    `ledger:${accountId}:${account?.role || "unknown"}`,
  );
  const requisitesQuery = useApiQuery(() => ownerAccountsApi.requisites(accountId), `owner-requisites:${accountId}`, account?.role === "user");
  const trafficQuery = useApiQuery(() => ownerAccountsApi.traffic(accountId), `owner-traffic:${accountId}`, account?.role === "user");

  function open(nextDialog: Dialog) {
    setMutationError(""); setAmount(""); setDescription(""); setPassword(""); setDialog(nextDialog);
  }

  async function runMutation(action: () => Promise<unknown>) {
    setSaving(true); setMutationError("");
    try {
      await action(); setDialog(null); await Promise.all([accountQuery.refetch(), walletQuery.refetch(), ledgerQuery.refetch()]);
    } catch (reason) {
      setMutationError(reason instanceof ApiError ? reason.message : "Не удалось выполнить операцию.");
    } finally { setSaving(false); }
  }

  async function saveProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await runMutation(() => ownerAccountsApi.update(accountId, {
      full_name: String(form.get("full_name")),
      email: String(form.get("email")) || null,
      phone: String(form.get("phone")) || null,
    }));
  }

  async function submitSimple(event: FormEvent) {
    event.preventDefault();
    if (dialog === "password") await runMutation(() => ownerAccountsApi.resetPassword(accountId, password));
    if (dialog === "allocate" || dialog === "insurance" || dialog === "adjust") {
      await runMutation(() => ownerAccountsApi.adjustWallet(accountId, dialog, amount, description));
    }
  }

  if (accountQuery.loading) return <div className={styles.state}>Загружаем профиль…</div>;
  if (accountQuery.error || !account) return <div className={`${styles.state} ${styles.error}`}>{accountQuery.error || "Аккаунт не найден"}<button onClick={accountQuery.refetch}>Повторить</button></div>;

  const wallet = walletQuery.data;
  const isMerchant = account.role === "merchant";
  return (
    <section>
      <Link href="/owner/accounts" className={styles.back}>← Назад к аккаунтам</Link>
      <div className={styles.header}>
        <div className={styles.identity}><div>{account.full_name.slice(0, 1).toUpperCase()}</div><span><small>{account.role.toUpperCase()}</small><h1>{account.full_name}</h1><p>@{account.username}</p></span></div>
        <div className={styles.headerActions}><button onClick={() => open("edit")}>Редактировать</button><button onClick={() => open("password")}>Сбросить пароль</button><button className={account.is_active ? styles.dangerButton : styles.successButton} onClick={() => void runMutation(() => ownerAccountsApi.setActive(account.id, !account.is_active))}>{account.is_active ? "Заблокировать" : "Разблокировать"}</button></div>
      </div>
      <div className={styles.infoGrid}>
        <article><span>СТАТУС</span><strong className={account.is_active ? styles.success : styles.danger}><i />{account.is_active ? "Активен" : "Заблокирован"}</strong></article>
        <article><span>EMAIL</span><strong>{account.email || "Не указан"}</strong></article>
        <article><span>ТЕЛЕФОН</span><strong>{account.phone || "Не указан"}</strong></article>
        <article><span>СОЗДАН</span><strong>{new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium" }).format(new Date(account.created_at))}</strong></article>
      </div>
      {account.role !== "owner" && <>
        <div className={styles.sectionTitle}><div><span>FINANCE</span><h2>{isMerchant ? "Кошелёк мерчанта" : "Кошелёк пользователя"}</h2></div>{!isMerchant && <div className={styles.walletActions}><button onClick={() => open("allocate")}>Выделить баланс</button><button onClick={() => open("insurance")}>Insurance</button><button onClick={() => open("adjust")}>Корректировка</button></div>}</div>
        <div className={styles.walletGrid}>
          {walletQuery.loading ? <div className={styles.walletState}>Загрузка кошелька…</div> : walletQuery.error ? <div className={`${styles.walletState} ${styles.error}`}>{walletQuery.error}</div> : wallet && <>
            <WalletCard label="Доступно" value={wallet.available_balance} accent />
            {"frozen_balance" in wallet && <WalletCard label="Заморожено" value={wallet.frozen_balance} />}
            {"insurance_balance" in wallet && <WalletCard label="Insurance" value={wallet.insurance_balance} />}
            {"held_balance" in wallet && <WalletCard label="Удерживается" value={wallet.held_balance} />}
          </>}
        </div>
        {!isMerchant && <div className={styles.userOperations}>
          <article><span>TRAFFIC</span><h2>Приём сделок</h2>{trafficQuery.loading ? <p>Загрузка…</p> : trafficQuery.error ? <p className={styles.error}>{trafficQuery.error}</p> : <strong className={trafficQuery.data?.is_enabled ? styles.success : styles.danger}>{trafficQuery.data?.is_enabled ? "Включён" : "Выключен"}</strong>}</article>
          <article><span>REQUISITES</span><h2>Реквизиты</h2>{requisitesQuery.loading ? <p>Загрузка…</p> : requisitesQuery.error ? <p className={styles.error}>{requisitesQuery.error}</p> : !requisitesQuery.data?.length ? <p>Реквизитов нет</p> : <div className={styles.requisiteList}>{requisitesQuery.data.map((item) => <div key={item.id}><strong>{item.masked_card_number}</strong><small>{item.bank_name} · {item.holder_name} · {item.is_active ? "активен" : "выключен"}</small></div>)}</div>}</article>
        </div>}
        <div className={styles.ledgerCard}><div className={styles.ledgerHeader}><div><span>TRANSACTIONS</span><h2>История операций</h2></div><button onClick={ledgerQuery.refetch}>Обновить</button></div>
          {ledgerQuery.loading ? <div className={styles.ledgerState}>Загрузка операций…</div> : ledgerQuery.error ? <div className={`${styles.ledgerState} ${styles.error}`}>{ledgerQuery.error}</div> : !ledgerQuery.data?.items.length ? <div className={styles.ledgerState}>Операций пока нет</div> : <div className={styles.tableScroll}><table><thead><tr><th>Дата</th><th>Тип</th><th>Описание</th><th>Сумма</th></tr></thead><tbody>{ledgerQuery.data.items.map((entry) => <tr key={entry.id}><td>{new Intl.DateTimeFormat("ru-RU", { dateStyle: "short", timeStyle: "short" }).format(new Date(entry.created_at))}</td><td>{entry.type}</td><td>{entry.description || "—"}</td><td className={Number(entry.amount) >= 0 ? styles.positive : styles.negative}>{Number(entry.amount) >= 0 ? "+" : ""}{entry.amount} {entry.currency.toUpperCase()}</td></tr>)}</tbody></table></div>}
        </div>
      </>}
      {dialog && <div className={styles.modalBackdrop} onMouseDown={() => setDialog(null)}><div className={styles.modal} onMouseDown={(e) => e.stopPropagation()}>
        <div className={styles.modalHeader}><div><span>ACCOUNT ACTION</span><h2>{dialogTitle(dialog)}</h2></div><button onClick={() => setDialog(null)}>×</button></div>
        {dialog === "edit" ? <form onSubmit={saveProfile} className={styles.form}><label>Полное имя<input name="full_name" required defaultValue={account.full_name} /></label><label>Email<input name="email" type="email" defaultValue={account.email || ""} /></label><label>Телефон<input name="phone" defaultValue={account.phone || ""} /></label>{mutationError && <div className={styles.formError}>{mutationError}</div>}<FormActions saving={saving} close={() => setDialog(null)} /></form> : <form onSubmit={submitSimple} className={styles.form}>
          {dialog === "password" ? <label>Новый пароль<input type="password" required minLength={8} maxLength={128} autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} /></label> : <><label>Сумма USDT<input type="number" required step="0.00000001" value={amount} onChange={(e) => setAmount(e.target.value)} /></label><label>{dialog === "adjust" ? "Причина" : "Описание"}<textarea required={dialog === "adjust"} maxLength={500} value={description} onChange={(e) => setDescription(e.target.value)} /></label></>}
          {mutationError && <div className={styles.formError}>{mutationError}</div>}<FormActions saving={saving} close={() => setDialog(null)} />
        </form>}
      </div></div>}
    </section>
  );
}

function WalletCard({ label, value, accent = false }: { label: string; value: string; accent?: boolean }) {
  return <article className={styles.walletCard}><span>{label}</span><strong className={accent ? styles.accent : ""}>{value}</strong><small>USDT</small></article>;
}

function FormActions({ saving, close }: { saving: boolean; close: () => void }) {
  return <div className={styles.formActions}><button type="button" onClick={close}>Отмена</button><button disabled={saving}>{saving ? "Сохраняем…" : "Подтвердить"}</button></div>;
}

function dialogTitle(dialog: Exclude<Dialog, null>) {
  return { edit: "Редактировать профиль", password: "Сбросить пароль", allocate: "Выделить баланс", insurance: "Изменить insurance", adjust: "Ручная корректировка" }[dialog];
}
