import type { ReactNode } from "react";

import { DashboardShell } from "@/components/layout/dashboard-shell";
import { RoleGate } from "@/features/auth/role-gate";

export default function UserLayout({ children }: { children: ReactNode }) {
  return <RoleGate role="user"><DashboardShell role="user">{children}</DashboardShell></RoleGate>;
}
