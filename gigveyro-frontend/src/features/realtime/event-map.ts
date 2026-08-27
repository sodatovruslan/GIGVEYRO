import type { UserRole } from "@/lib/api/types";

export const realtimeEventNames = [
  "deal.created",
  "deal.accepted",
  "deal.completed",
  "deal.released",
  "deal.expired",
  "deal.disputed",
  "fiat.allocated",
  "fiat.converted",
] as const;

export type RealtimeEventName = (typeof realtimeEventNames)[number];

const ownerCore = ["owner-deals", "owner-summary", "owner-activity", "analytics:*"];
const userDeals = ["user-deals", "user-appeal-deals"];
const userFunds = ["user-wallet", "wallet-page", "ledger-page"];
const merchantDeals = ["merchant-deals", "merchant-appeal-deals"];
const merchantFunds = ["merchant-dashboard-wallet", "merchant-wallet", "merchant-ledger"];

export function queryKeysForRealtimeEvent(event: RealtimeEventName, role: UserRole) {
  if (event === "fiat.allocated" || event === "fiat.converted") {
    return role === "owner"
      ? ["owner-fiat:*"]
      : role === "user"
        ? ["user-fiat:*"]
        : [];
  }
  if (role === "owner") {
    return event === "deal.disputed" ? [...ownerCore, "owner-appeals"] : ownerCore;
  }

  if (role === "merchant") {
    if (event === "deal.completed" || event === "deal.released") {
      return [...merchantDeals, ...merchantFunds];
    }
    if (event === "deal.disputed") return [...merchantDeals, "merchant-appeals"];
    return merchantDeals;
  }

  if (event === "deal.created" || event === "deal.expired") return ["available-deals"];
  if (event === "deal.accepted") {
    return ["available-deals", ...userDeals, ...userFunds];
  }
  if (event === "deal.completed" || event === "deal.released") {
    return [...userDeals, ...userFunds];
  }
  return [...userDeals, "user-appeals"];
}
