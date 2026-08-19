import { apiFetch } from "@/lib/api/client";
import type { Deposit, DepositStatus, Paginated } from "@/lib/api/types";

export const depositsApi = {
  list: (owner: boolean, status?: DepositStatus) => apiFetch<Paginated<Deposit>>(`${owner ? "/owner" : ""}/deposits?limit=100&offset=0${status ? `&status=${status}` : ""}`),
  create: (amount: string) => apiFetch<Deposit>("/deposits", { method: "POST", body: { amount } }),
};
