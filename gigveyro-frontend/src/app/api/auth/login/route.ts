import { type NextRequest, NextResponse } from "next/server";

import type { Account, LoginInput, TokenResponse } from "@/lib/api/types";
import { ACCESS_COOKIE, authCookieOptions, backendFetch, REFRESH_COOKIE } from "@/lib/server/backend";

export async function POST(request: NextRequest) {
  const origin = request.headers.get("origin");
  if (origin && origin !== request.nextUrl.origin) {
    return NextResponse.json({ detail: "Invalid request origin" }, { status: 403 });
  }
  const payload = (await request.json().catch(() => null)) as LoginInput | null;
  if (!payload?.username || !payload.password) {
    return NextResponse.json({ detail: "Введите логин и пароль" }, { status: 400 });
  }

  const tokenResponse = await backendFetch("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!tokenResponse.ok) {
    return new NextResponse(await tokenResponse.arrayBuffer(), {
      status: tokenResponse.status,
      headers: { "Content-Type": tokenResponse.headers.get("content-type") || "application/json" },
    });
  }

  const tokens = (await tokenResponse.json()) as TokenResponse;
  const accountResponse = await backendFetch("/auth/me", {
    headers: { Authorization: `Bearer ${tokens.access_token}` },
  });
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
