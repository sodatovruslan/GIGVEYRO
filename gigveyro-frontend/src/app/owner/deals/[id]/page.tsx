"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { useTranslations } from "next-intl";

import { DealDetailGrid } from "@/components/deals/deal-detail";
import { useLocalizedError } from "@/features/i18n/use-localized-error";
import { dealsApi } from "@/lib/api/deals";
import { useApiQuery } from "@/lib/hooks/use-api-query";

import styles from "@/components/deals/deals-page.module.css";

export default function OwnerDealDetailPage() {
  const t = useTranslations("deals");
  const localizeError = useLocalizedError();
  const id = useParams<{ id: string }>().id;
  const query = useApiQuery(() => dealsApi.ownerGet(id), `owner-deal:${id}`);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function act(action: "complete" | "release") {
    setSaving(true); setError("");
    try { await dealsApi.ownerAction(id, action); await query.refetch(); }
    catch (reason) {
      setError(localizeError(reason));
      // The deal may already have moved to another status - refetch so a
      // stale action button doesn't stay clickable against outdated state.
      await query.refetch();
    }
    finally { setSaving(false); }
  }

  const deal = query.data;
  return <section>
    <Link href="/owner/deals" className={styles.back}>{t("backToDeals")}</Link>
    {query.loading ? <div className={styles.state}>{t("loading")}</div> : query.error ? <div className={`${styles.state} ${styles.errorText}`}>{query.error}</div> : deal && <>
      <div className={styles.heading}>
        <div><span>{t("eyebrow")}</span><h1>{deal.public_id}</h1></div>
        {["accepted", "payment_pending"].includes(deal.status) && <div className={styles.rowActions}><button disabled={saving} onClick={() => void act("complete")}>{t("complete")}</button><button disabled={saving} onClick={() => void act("release")}>{t("release")}</button></div>}
      </div>
      {error && <div className={styles.error}>{error}</div>}
      <DealDetailGrid deal={deal} />
    </>}
  </section>;
}
