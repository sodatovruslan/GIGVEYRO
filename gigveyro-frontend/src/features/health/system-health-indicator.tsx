"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { healthStatusFromPayload, type SystemHealthStatus } from "./system-health";

const POLL_INTERVAL_MS = 30_000;

export function SystemHealthIndicator({ className }: { className?: string }) {
  const t = useTranslations("header");
  const [status, setStatus] = useState<SystemHealthStatus>("checking");

  useEffect(() => {
    let active = true;
    let controller: AbortController | null = null;

    async function check() {
      controller?.abort();
      controller = new AbortController();
      try {
        const response = await fetch("/api/health", {
          cache: "no-store",
          signal: controller.signal,
        });
        const payload = await response.json().catch(() => null);
        if (active) setStatus(healthStatusFromPayload(response.ok, payload));
      } catch {
        if (active && !controller.signal.aborted) setStatus("unavailable");
      }
    }

    void check();
    const interval = window.setInterval(() => void check(), POLL_INTERVAL_MS);
    return () => {
      active = false;
      controller?.abort();
      window.clearInterval(interval);
    };
  }, []);

  return <div className={className} data-health={status}><i />{t(status)}</div>;
}
