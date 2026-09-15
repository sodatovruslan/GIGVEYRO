"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { useAppFormat } from "@/features/i18n/use-app-format";
import { useEnumLabels } from "@/features/i18n/use-enum-labels";
import { useLocalizedError } from "@/features/i18n/use-localized-error";
import { ownerAccountsApi } from "@/lib/api/owner-accounts";
import { ownerOperationsApi } from "@/lib/api/owner-operations";
import { ownerTeamLeadsApi } from "@/lib/api/owner-team-leads";
import type { MerchantWallet, Wallet } from "@/lib/api/types";
import { useApiQuery } from "@/lib/hooks/use-api-query";

import styles from "./account.module.css";
import { FiatWalletPanel } from "./fiat-wallet-panel";

type Dialog = "edit" | "password" | "allocate" | "insurance" | "adjust" | "reservePercent" | null;

export default function OwnerAccountDetailsPage() {
  const t = useTranslations("accounts");
  const common = useTranslations("common");
  const walletText = useTranslations("wallet");
  const trafficText = useTranslations("traffic");
  const requisitesText = useTranslations("requisites");
  const labels = useEnumLabels();
  const format = useAppFormat();
  const localizeError = useLocalizedError();
  const accountId = useParams<{ accountId: string }>().accountId;
  const [dialog, setDialog] = useState<Dialog>(null);
  const [mutationError, setMutationError] = useState("");
  const [saving, setSaving] = useState(false);
  const [password, setPassword] = useState("");
  const [amount, setAmount] = useState("");
  const [description, setDescription] = useState("");
  const [successMessage, setSuccessMessage] = useState("");
  const accountQuery = useApiQuery(() => ownerAccountsApi.get(accountId), `account:${accountId}`);
  const account = accountQuery.data;
  const walletQuery = useApiQuery<Wallet | MerchantWallet>(() => account?.role === "merchant" ? ownerAccountsApi.merchantWallet(accountId) : ownerAccountsApi.userWallet(accountId), `wallet:${accountId}:${account?.role || "unknown"}`);
  const ledgerQuery = useApiQuery(() => ownerAccountsApi.ledger(accountId, account?.role === "merchant"), `ledger:${accountId}:${account?.role || "unknown"}`);
  const requisitesQuery = useApiQuery(() => ownerAccountsApi.requisites(accountId), `owner-requisites:${accountId}`, account?.role === "user");
  const trafficQuery = useApiQuery(() => ownerAccountsApi.traffic(accountId), `owner-traffic:${accountId}`, account?.role === "user");
  const teamLeadsQuery = useApiQuery(() => ownerAccountsApi.list({ role: "team_lead", limit: 100 }), "owner-team-leads-options", account?.role === "user");
  const [teamLeadSaving, setTeamLeadSaving] = useState(false);
  const [teamLeadError, setTeamLeadError] = useState("");
  const reserveQuery = useApiQuery(() => ownerAccountsApi.insuranceReserve(accountId), `insurance-reserve:${accountId}`, account?.role === "user");
  const [reservePercent, setReservePercent] = useState("");
  const [reserveEnabled, setReserveEnabled] = useState(true);

  async function saveReservePolicy(event: FormEvent) {
    event.preventDefault();
    setSaving(true); setMutationError("");
    try {
      const draft = await ownerOperationsApi.createInsuranceReservePolicy({ enabled: reserveEnabled, minimum_reserve_percentage: reservePercent });
      await ownerOperationsApi.activateInsuranceReservePolicy(draft.id);
      setDialog(null);
      setSuccessMessage(t("reservePercentChanged"));
      await reserveQuery.refetch();
    } catch (reason) { setMutationError(localizeError(reason)); }
    finally { setSaving(false); }
  }

  async function assignTeamLead(teamLeadId: string) {
    setTeamLeadSaving(true); setTeamLeadError("");
    try { await ownerTeamLeadsApi.assign(accountId, teamLeadId || null); await accountQuery.refetch(); }
    catch (reason) { setTeamLeadError(localizeError(reason)); }
    finally { setTeamLeadSaving(false); }
  }

  useEffect(() => {
    if (!successMessage) return;
    const timeout = window.setTimeout(() => setSuccessMessage(""), 3500);
    return () => window.clearTimeout(timeout);
  }, [successMessage]);

  function open(nextDialog: Dialog) { setMutationError(""); setAmount(""); setDescription(""); setPassword(""); if (nextDialog === "reservePercent" && reserveQuery.data) { setReservePercent(reserveQuery.data.minimum_reserve_percentage); setReserveEnabled(reserveQuery.data.policy_enabled); } setDialog(nextDialog); }
  async function runMutation(action: () => Promise<unknown>, options: { refresh?: boolean; success?: string } = {}) { setSaving(true); setMutationError(""); try { await action(); setDialog(null); if (options.success) setSuccessMessage(options.success); if (options.refresh !== false) await Promise.all([accountQuery.refetch(), walletQuery.refetch(), ledgerQuery.refetch()]); } catch (reason) { setMutationError(localizeError(reason)); } finally { setSaving(false); } }
  async function saveProfile(event: FormEvent<HTMLFormElement>) { event.preventDefault(); const form = new FormData(event.currentTarget); await runMutation(() => ownerAccountsApi.update(accountId, { full_name: String(form.get("full_name")), email: String(form.get("email")) || null, phone: String(form.get("phone")) || null })); }
  async function submitSimple(event: FormEvent) { event.preventDefault(); if (dialog === "password") await runMutation(() => ownerAccountsApi.resetPassword(accountId, password), { refresh: false, success: t("passwordChanged") }); if (dialog === "allocate" || dialog === "insurance" || dialog === "adjust") await runMutation(() => ownerAccountsApi.adjustWallet(accountId, dialog, amount, description)); }

  if (accountQuery.loading) return <div className={styles.state}>{t("loadingProfile")}</div>;
  if (accountQuery.error || !account) return <div className={`${styles.state} ${styles.error}`}>{accountQuery.error || t("profileNotFound")}<button onClick={accountQuery.refetch}>{common("retry")}</button></div>;

  const wallet = walletQuery.data;
  const isMerchant = account.role === "merchant";
  const isUser = account.role === "user";
  const walletLabel = isMerchant ? t("merchantWallet") : account.role === "team_lead" ? t("teamLeadWallet") : t("userWallet");
  const dialogTitle = (value: Exclude<Dialog, null>) => ({ edit: t("editTitle"), password: t("passwordTitle"), allocate: t("allocateTitle"), insurance: t("insuranceTitle"), adjust: t("adjustTitle"), reservePercent: t("reservePercentTitle") })[value];

  return <section>
    {successMessage && <div className={styles.toast} role="status" aria-live="polite"><i />{successMessage}</div>}
    <Link href="/owner/accounts" className={styles.back}>{t("back")}</Link>
    <div className={styles.header}><div className={styles.identity}><div>{account.full_name.slice(0, 1).toUpperCase()}</div><span><small>{labels.role(account.role)}</small><h1>{account.full_name}</h1><p>@{account.username}</p></span></div><div className={styles.headerActions}><button onClick={() => open("edit")}>{t("editProfile")}</button><button onClick={() => open("password")}>{t("resetPassword")}</button><button className={account.is_active ? styles.dangerButton : styles.successButton} onClick={() => void runMutation(() => ownerAccountsApi.setActive(account.id, !account.is_active))}>{account.is_active ? t("block") : t("unblock")}</button></div></div>
    <div className={styles.infoGrid}><article><span>{common("status")}</span><strong className={account.is_active ? styles.success : styles.danger}><i />{account.is_active ? common("active") : t("blocked")}</strong></article><article><span>{t("email")}</span><strong>{account.email || common("notSpecified")}</strong></article><article><span>{t("phone")}</span><strong>{account.phone || common("notSpecified")}</strong></article><article><span>{t("created")}</span><strong>{format.date(account.created_at)}</strong></article></div>
    {isUser && <div className={styles.userOperations}>
      <article>
        <span>{t("teamLeadEyebrow")}</span>
        <h2>{t("assignedTeamLead")}</h2>
        {teamLeadsQuery.loading ? <p>{common("loading")}</p> : teamLeadsQuery.error ? <p className={styles.error}>{teamLeadsQuery.error}</p> : <select disabled={teamLeadSaving} value={account.team_lead_id || ""} onChange={(event) => void assignTeamLead(event.target.value)}>
          <option value="">{t("noTeamLead")}</option>
          {teamLeadsQuery.data?.items.map((lead) => <option key={lead.id} value={lead.id}>{lead.full_name} (@{lead.username})</option>)}
        </select>}
        {teamLeadError && <p className={styles.error}>{teamLeadError}</p>}
      </article>
    </div>}
    {account.role !== "owner" && <><div className={styles.sectionTitle}><div><span>{t("finance")}</span><h2>{walletLabel}</h2></div>{isUser && <div className={styles.walletActions}><button onClick={() => open("allocate")}>{t("allocate")}</button><button onClick={() => open("insurance")}>{t("insurance")}</button><button onClick={() => open("adjust")}>{t("adjust")}</button></div>}</div>
      <div className={styles.walletGrid}>{walletQuery.loading ? <div className={styles.walletState}>{walletText("loadingOperations")}</div> : walletQuery.error ? <div className={`${styles.walletState} ${styles.error}`}>{walletQuery.error}</div> : wallet && <><WalletCard label={walletText("available")} value={wallet.available_balance} accent />{"frozen_balance" in wallet && <WalletCard label={walletText("frozen")} value={wallet.frozen_balance} />}{"insurance_balance" in wallet && <WalletCard label={walletText("insurance")} value={wallet.insurance_balance} />}{"held_balance" in wallet && <WalletCard label={walletText("held")} value={wallet.held_balance} />}</>}</div>
      {isUser && <><div className={styles.sectionTitle}><div><span>{t("insuranceReserveEyebrow")}</span><h2>{t("insuranceReserveTitle")}</h2></div><button onClick={() => open("reservePercent")}>{t("changeReservePercent")}</button></div>
        <div className={styles.walletGrid}>{reserveQuery.loading ? <div className={styles.walletState}>{walletText("loadingOperations")}</div> : reserveQuery.error ? <div className={`${styles.walletState} ${styles.error}`}>{reserveQuery.error}</div> : reserveQuery.data && <>
          <WalletCard label={t("currentReservePercent")} value={reserveQuery.data.minimum_reserve_percentage} unit="%" />
          <WalletCard label={t("insuranceBalanceLabel")} value={reserveQuery.data.insurance_balance} />
          <WalletCard label={t("requiredMinimumReserve")} value={reserveQuery.data.required_minimum_reserve} />
          <WalletCard label={t("availableAboveReserve")} value={reserveQuery.data.available_above_reserve} accent />
        </>}</div>
        {reserveQuery.data && <div className={styles.infoGrid}>
          <article><span>{t("reservePolicyStatus")}</span><strong className={reserveQuery.data.policy_enabled ? styles.success : styles.danger}>{reserveQuery.data.policy_enabled ? common("enabled") : common("disabled")}</strong></article>
          <article><span>{t("reservePolicyVersion")}</span><strong>{reserveQuery.data.policy_version}</strong></article>
          <article><span>{t("reservePolicyUpdated")}</span><strong>{format.date(reserveQuery.data.policy_updated_at)}</strong></article>
        </div>}
      </>}
      {isUser && <FiatWalletPanel accountId={accountId} />}
      {isUser && <div className={styles.userOperations}><article><span>{trafficText("eyebrow")}</span><h2>{trafficText("title")}</h2>{trafficQuery.loading ? <p>{common("loading")}</p> : trafficQuery.error ? <p className={styles.error}>{trafficQuery.error}</p> : <strong className={trafficQuery.data?.is_enabled ? styles.success : styles.danger}>{trafficQuery.data?.is_enabled ? common("enabled") : common("disabled")}</strong>}</article><article><span>{requisitesText("eyebrow")}</span><h2>{requisitesText("title")}</h2>{requisitesQuery.loading ? <p>{common("loading")}</p> : requisitesQuery.error ? <p className={styles.error}>{requisitesQuery.error}</p> : !requisitesQuery.data?.length ? <p>{t("noRequisites")}</p> : <div className={styles.requisiteList}>{requisitesQuery.data.map((item) => <div key={item.id}><strong>{item.masked_card_number}</strong><small>{item.bank_name} · {item.holder_name} · {item.is_active ? common("active") : common("disabled")}</small></div>)}</div>}</article></div>}
      <div className={styles.ledgerCard}><div className={styles.ledgerHeader}><div><span>{t("transactionsEyebrow")}</span><h2>{t("transactions")}</h2></div><button onClick={ledgerQuery.refetch}>{common("refresh")}</button></div>{ledgerQuery.loading ? <div className={styles.ledgerState}>{walletText("loadingOperations")}</div> : ledgerQuery.error ? <div className={`${styles.ledgerState} ${styles.error}`}>{ledgerQuery.error}</div> : !ledgerQuery.data?.items.length ? <div className={styles.ledgerState}>{t("noOperations")}</div> : <div className={styles.tableScroll}><table><thead><tr><th>{common("date")}</th><th>{common("type")}</th><th>{common("description")}</th><th>{common("amount")}</th></tr></thead><tbody>{ledgerQuery.data.items.map((entry) => <tr key={entry.id}><td>{format.dateTime(entry.created_at)}</td><td>{labels.ledger(entry.type)}</td><td>{entry.description || "—"}</td><td className={Number(entry.amount) >= 0 ? styles.positive : styles.negative}>{Number(entry.amount) >= 0 ? "+" : ""}{entry.amount} {entry.currency.toUpperCase()}</td></tr>)}</tbody></table></div>}</div>
    </>}
    {dialog && <div className={styles.modalBackdrop} onMouseDown={() => setDialog(null)}><div className={styles.modal} onMouseDown={(event) => event.stopPropagation()}><div className={styles.modalHeader}><div><span>{t("actionEyebrow")}</span><h2>{dialogTitle(dialog)}</h2></div><button onClick={() => setDialog(null)} aria-label={t("close")}>×</button></div>{dialog === "edit" ? <form onSubmit={saveProfile} className={styles.form}><label>{t("fullName")}<input name="full_name" required defaultValue={account.full_name} /></label><label>{t("email")}<input name="email" type="email" defaultValue={account.email || ""} /></label><label>{t("phone")}<input name="phone" defaultValue={account.phone || ""} /></label>{mutationError && <div className={styles.formError}>{mutationError}</div>}<FormActions /></form> : dialog === "reservePercent" ? <form onSubmit={saveReservePolicy} className={styles.form}><p>{t("reservePercentHint")}</p><label>{t("reservePercentLabel")}<input type="number" required min="0" max="100" step="0.01" value={reservePercent} onChange={(event) => setReservePercent(event.target.value)} /></label><label className={styles.checkboxLabel}><input type="checkbox" checked={reserveEnabled} onChange={(event) => setReserveEnabled(event.target.checked)} />{t("reservePolicyEnabledLabel")}</label>{mutationError && <div className={styles.formError}>{mutationError}</div>}<FormActions /></form> : <form onSubmit={submitSimple} className={styles.form}>{dialog === "password" ? <label>{t("newPassword")}<input type="password" required minLength={8} maxLength={128} autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} /></label> : <><label>{t("amountUsdt")}<input type="number" required step="0.00000001" value={amount} onChange={(event) => setAmount(event.target.value)} /></label><label>{dialog === "adjust" ? t("reason") : common("description")}<textarea required={dialog === "adjust"} maxLength={500} value={description} onChange={(event) => setDescription(event.target.value)} /></label></>}{mutationError && <div className={styles.formError}>{mutationError}</div>}<FormActions /></form>}</div></div>}
  </section>;

  function WalletCard({ label, value, accent = false, unit = "USDT" }: { label: string; value: string; accent?: boolean; unit?: string }) { return <article className={styles.walletCard}><span>{label}</span><strong className={accent ? styles.accent : ""}>{format.number(value)}</strong><small>{unit}</small></article>; }
  function FormActions() { return <div className={styles.formActions}><button type="button" onClick={() => setDialog(null)}>{common("cancel")}</button><button disabled={saving}>{saving ? common("saving") : common("confirm")}</button></div>; }
}
