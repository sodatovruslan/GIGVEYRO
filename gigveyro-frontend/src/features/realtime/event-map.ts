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
  "payout.updated",
  "withdrawal.updated",
  "deposit.updated",
] as const;

export type RealtimeEventName = (typeof realtimeEventNames)[number];

const ownerCore = ["owner-deals", "owner-summary", "owner-activity", "analytics:*"];
const userDeals = ["user-deals", "user-appeal-deals"];
const userFunds = ["user-wallet", "wallet-page", "ledger-page"];
const merchantDeals = ["merchant-deals", "merchant-appeal-deals"];
const merchantFunds = ["merchant-dashboard-wallet", "merchant-wallet", "merchant-ledger"];
const ownerPayouts = ["owner-payouts:*", "owner-payout:*"];
const ownerWithdrawals = ["owner-withdrawals:*", "owner-withdrawal:*"];
const merchantWithdrawals = ["merchant-withdrawals:*", "merchant-withdrawal:*"];

export function queryKeysForRealtimeEvent(event: RealtimeEventName, role: UserRole) {
  if (event === "deposit.updated") {
    if (role === "owner") return ["deposits:*", "unmatched-transfers:*", "owner-summary", "owner-activity"];
    if (role === "user") return ["deposits:*", ...userFunds];
    return [];
  }
  if (event === "payout.updated") {
    if (role === "owner") return [...ownerPayouts, "owner-summary", "owner-activity"];
    if (role === "merchant") {
      return [...merchantWithdrawals, "merchant-dashboard-withdrawals", ...merchantFunds];
    }
    return [];
  }
  if (event === "withdrawal.updated") {
    if (role === "owner") {
      return [...ownerWithdrawals, ...ownerPayouts, "owner-summary", "owner-activity"];
    }
    if (role === "merchant") {
      return [...merchantWithdrawals, "merchant-dashboard-withdrawals", ...merchantFunds];
    }
    return [];
  }
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
