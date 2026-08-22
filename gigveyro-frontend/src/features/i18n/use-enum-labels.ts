"use client";

import { useTranslations } from "next-intl";

export function useEnumLabels() {
  const t = useTranslations("enums");

  return {
    role: (value: string) => t(`role.${value}`),
    deal: (value: string) => t(`deal.${value}`),
    appeal: (value: string) => t(`appeal.${value}`),
    appealReason: (value: string) => t(`appealReason.${value}`),
    withdrawal: (value: string) => t(`withdrawal.${value}`),
    deposit: (value: string) => t(`deposit.${value}`),
    ledger: (value: string) => t(`ledger.${value}`),
    notification: (value: string) => t(`notification.${value}`),
    destination: (value: string) => t(`destination.${value}`),
  };
}
