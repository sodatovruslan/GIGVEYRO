"use client";

import { type ReactNode, useEffect } from "react";

import { useAuth } from "@/features/auth/auth-provider";
import { queryKeysForRealtimeEvent } from "@/features/realtime/event-map";
import {
  RealtimeClient,
  type RealtimeTicket,
  resolveRealtimeUrl,
} from "@/features/realtime/realtime-client";
import { apiFetch } from "@/lib/api/client";
import { queryInvalidation } from "@/lib/query/invalidation";

export function RealtimeProvider({ children }: { children: ReactNode }) {
  const { account, status } = useAuth();

  useEffect(() => {
    if (status !== "authenticated" || !account) return;
    const client = new RealtimeClient({
      getTicket: () => apiFetch<RealtimeTicket>("/api/v1/realtime/ticket", { method: "POST" }),
      createSocket: (url, protocols) => new WebSocket(url, protocols),
      resolveUrl: resolveRealtimeUrl,
      onEvent: (event) => {
        queryInvalidation.invalidate(queryKeysForRealtimeEvent(event.event, account.role));
      },
    });
    client.start();
    return () => client.stop();
  }, [account, status]);

  return children;
}
