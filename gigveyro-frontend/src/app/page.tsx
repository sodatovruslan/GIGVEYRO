"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useTranslations } from "next-intl";

import { FullPageLoader } from "@/components/ui/full-page-loader";
import { useAuth } from "@/features/auth/auth-provider";
import { dashboardPath } from "@/features/auth/roles";

export default function Home() {
  const t = useTranslations("auth");
  const router = useRouter();
  const { account, status } = useAuth();

  useEffect(() => {
    if (status === "anonymous") router.replace("/login");
    if (status === "authenticated" && account) router.replace(dashboardPath(account.role));
  }, [account, router, status]);

  return <FullPageLoader label={t("checkingAccess")} />;
}
