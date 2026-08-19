import type { ReactNode } from "react";

import { DashboardShell } from "@/components/layout/dashboard-shell";
import { RoleGate } from "@/features/auth/role-gate";

export default function OwnerLayout({ children }: { children: ReactNode }) {
  return <RoleGate role="owner"><DashboardShell role="owner">{children}</DashboardShell></RoleGate>;
}
