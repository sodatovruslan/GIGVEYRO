"use client";

import type { ReactNode } from "react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useTranslations } from "next-intl";

import { FullPageLoader } from "@/components/ui/full-page-loader";
import { useAuth } from "@/features/auth/auth-provider";
import { dashboardPath } from "@/features/auth/roles";
import type { UserRole } from "@/lib/api/types";

export function RoleGate({ role, children }: { role: UserRole; children: ReactNode }) {
  const router = useRouter();
  const { account, status } = useAuth();
  const t = useTranslations("auth");

  useEffect(() => {
    if (status === "anonymous") router.replace("/login");
    if (status === "authenticated" && account && account.role !== role) {
      router.replace(dashboardPath(account.role));
    }
  }, [account, role, router, status]);

  if (status !== "authenticated" || !account || account.role !== role) {
    return <FullPageLoader label={t("checkingAccess")} />;
  }
  return children;
}
