import type { ReactNode } from "react";

import { DashboardShell } from "@/components/layout/dashboard-shell";
import { RoleGate } from "@/features/auth/role-gate";

export default function TeamLeadLayout({ children }: { children: ReactNode }) {
  return <RoleGate role="team_lead"><DashboardShell role="team_lead">{children}</DashboardShell></RoleGate>;
}
