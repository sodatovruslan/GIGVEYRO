import { type NextRequest, NextResponse } from "next/server";

import type { Account, TwoFactorSetupConfirmResult } from "@/lib/api/types";
import { ACCESS_COOKIE, authCookieOptions, backendFetch, REFRESH_COOKIE } from "@/lib/server/backend";
import { isTrustedOrigin } from "@/lib/server/origin";

interface ConfirmInput { setup_token: string; totp_code: string }

export async function POST(request: NextRequest) {
  if (!isTrustedOrigin(request)) {
    return NextResponse.json({ detail: "Invalid request origin" }, { status: 403 });
  }
  const payload = (await request.json().catch(() => null)) as ConfirmInput | null;
  if (!payload?.setup_token || !payload.totp_code) {
    return NextResponse.json({ detail: "Введите код подтверждения" }, { status: 400 });
  }

  let response: Response;
  try {
    response = await backendFetch("/auth/2fa/setup/confirm", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${payload.setup_token}`,
      },
      body: JSON.stringify({ totp_code: payload.totp_code }),
    });
  } catch {
    return NextResponse.json({ detail: "Backend временно недоступен" }, { status: 502 });
  }
  if (!response.ok) {
    return new NextResponse(await response.arrayBuffer(), {
      status: response.status,
      headers: { "Content-Type": response.headers.get("content-type") || "application/json" },
    });
  }

  const body = (await response.json()) as TwoFactorSetupConfirmResult;
  if (!body.access_token || !body.refresh_token) {
    // Should not happen for the forced-onboarding path, but fail closed
    // rather than pretend a session exists.
    return NextResponse.json({ detail: "Setup did not return a session" }, { status: 502 });
  }

  let accountResponse: Response;
  try {
    accountResponse = await backendFetch("/auth/me", {
      headers: { Authorization: `Bearer ${body.access_token}` },
    });
  } catch {
    return NextResponse.json({ detail: "Backend временно недоступен" }, { status: 502 });
  }
  if (!accountResponse.ok) {
    return NextResponse.json({ detail: "Не удалось получить профиль аккаунта" }, { status: 502 });
  }

  const account = (await accountResponse.json()) as Account;
  const result = NextResponse.json({
    account,
    recovery_codes: body.recovery_codes,
    enabled_at: body.enabled_at,
  });
  result.cookies.set(ACCESS_COOKIE, body.access_token, {
    ...authCookieOptions,
    maxAge: body.access_expires_in,
  });
  result.cookies.set(REFRESH_COOKIE, body.refresh_token, {
    ...authCookieOptions,
    maxAge: 60 * 60 * 24 * 30,
  });
  return result;
}
