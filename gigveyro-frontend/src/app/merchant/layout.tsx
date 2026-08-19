import type { ReactNode } from "react";

import { DashboardShell } from "@/components/layout/dashboard-shell";
import { RoleGate } from "@/features/auth/role-gate";

export default function MerchantLayout({ children }: { children: ReactNode }) {
  return <RoleGate role="merchant"><DashboardShell role="merchant">{children}</DashboardShell></RoleGate>;
}
