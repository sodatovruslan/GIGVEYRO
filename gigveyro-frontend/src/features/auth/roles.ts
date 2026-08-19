import type { UserRole } from "@/lib/api/types";

export function dashboardPath(role: UserRole) {
  return `/${role}`;
}
