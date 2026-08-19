import "server-only";

import type { TokenResponse } from "@/lib/api/types";

export const ACCESS_COOKIE = "gigveyro_access";
export const REFRESH_COOKIE = "gigveyro_refresh";

const backendUrl = process.env.BACKEND_API_URL || "http://127.0.0.1:8000";

export function backendFetch(path: string, init: RequestInit = {}) {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return fetch(`${backendUrl.replace(/\/$/, "")}${normalizedPath}`, { ...init, cache: "no-store" });
}

export async function refreshTokens(refreshToken: string): Promise<TokenResponse | null> {
  const response = await backendFetch("/auth/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  if (!response.ok) return null;
  return (await response.json()) as TokenResponse;
}

export const authCookieOptions = {
  httpOnly: true,
  secure: process.env.NODE_ENV === "production",
  sameSite: "lax" as const,
  path: "/",
};
