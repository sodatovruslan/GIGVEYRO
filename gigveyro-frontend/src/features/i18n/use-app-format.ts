"use client";

import { useFormatter } from "next-intl";

export function useAppFormat() {
  const format = useFormatter();

  return {
    date: (value: string | Date) => format.dateTime(new Date(value), { dateStyle: "medium" }),
    dateTime: (value: string | Date) => format.dateTime(new Date(value), { dateStyle: "short", timeStyle: "short" }),
    time: (value: string | Date) => format.dateTime(new Date(value), { timeStyle: "short" }),
    number: (value: string | number, maximumFractionDigits = 8) => format.number(Number(value), { maximumFractionDigits }),
  };
}
