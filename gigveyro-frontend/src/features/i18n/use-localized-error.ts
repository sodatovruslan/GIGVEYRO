"use client";

import { useCallback } from "react";
import { useTranslations } from "next-intl";

import { ApiError } from "@/lib/api/error";

export function useLocalizedError() {
  const t = useTranslations("errors");
  return useCallback((reason: unknown) => {
    if (!(reason instanceof ApiError)) return t("generic");
    const key = String(reason.status) as "400" | "401" | "403" | "404" | "409" | "422" | "429" | "500";
    return [400, 401, 403, 404, 409, 422, 429, 500].includes(reason.status)
      ? t(key)
      : reason.status === 0
        ? t("connection")
        : t("generic");
  }, [t]);
}
