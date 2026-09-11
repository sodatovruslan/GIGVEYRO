import { type NextRequest, NextResponse } from "next/server";

import type { Account, TokenResponse } from "@/lib/api/types";
import { ACCESS_COOKIE, authCookieOptions, backendFetch, REFRESH_COOKIE } from "@/lib/server/backend";
import { isTrustedOrigin } from "@/lib/server/origin";

interface VerifyInput { challenge_token: string; code: string }

export async function POST(request: NextRequest) {
  if (!isTrustedOrigin(request)) {
    return NextResponse.json({ detail: "Invalid request origin" }, { status: 403 });
  }
  const payload = (await request.json().catch(() => null)) as VerifyInput | null;
  if (!payload?.challenge_token || !payload.code) {
    return NextResponse.json({ detail: "Введите код подтверждения" }, { status: 400 });
  }

  let tokenResponse: Response;
  try {
    tokenResponse = await backendFetch("/auth/2fa/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch {
    return NextResponse.json({ detail: "Backend временно недоступен" }, { status: 502 });
  }
  if (!tokenResponse.ok) {
    return new NextResponse(await tokenResponse.arrayBuffer(), {
      status: tokenResponse.status,
      headers: { "Content-Type": tokenResponse.headers.get("content-type") || "application/json" },
    });
  }

  const tokens = (await tokenResponse.json()) as TokenResponse;
  let accountResponse: Response;
  try {
    accountResponse = await backendFetch("/auth/me", {
      headers: { Authorization: `Bearer ${tokens.access_token}` },
    });
  } catch {
    return NextResponse.json({ detail: "Backend временно недоступен" }, { status: 502 });
  }
  if (!accountResponse.ok) {
    return NextResponse.json({ detail: "Не удалось получить профиль аккаунта" }, { status: 502 });
  }

  const account = (await accountResponse.json()) as Account;
  const response = NextResponse.json(account);
  response.cookies.set(ACCESS_COOKIE, tokens.access_token, {
    ...authCookieOptions,
    maxAge: tokens.access_expires_in,
  });
  response.cookies.set(REFRESH_COOKIE, tokens.refresh_token, {
    ...authCookieOptions,
    maxAge: 60 * 60 * 24 * 30,
  });
  return response;
}
