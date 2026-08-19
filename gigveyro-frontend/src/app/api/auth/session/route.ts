import { type NextRequest, NextResponse } from "next/server";

import type { Account } from "@/lib/api/types";
import {
  ACCESS_COOKIE,
  authCookieOptions,
  backendFetch,
  REFRESH_COOKIE,
  refreshTokens,
} from "@/lib/server/backend";

function readAccount(accessToken: string) {
  return backendFetch("/auth/me", { headers: { Authorization: `Bearer ${accessToken}` } });
}

export async function GET(request: NextRequest) {
  let accessToken = request.cookies.get(ACCESS_COOKIE)?.value;
  const refreshToken = request.cookies.get(REFRESH_COOKIE)?.value;
  let renewed = null;
  let accountResponse = accessToken ? await readAccount(accessToken) : null;

  if ((!accountResponse || accountResponse.status === 401) && refreshToken) {
    renewed = await refreshTokens(refreshToken);
    if (renewed) {
      accessToken = renewed.access_token;
      accountResponse = await readAccount(accessToken);
    }
  }

  if (!accountResponse?.ok) {
    const response = NextResponse.json({ detail: "Сессия отсутствует" }, { status: 401 });
    response.cookies.set(ACCESS_COOKIE, "", { ...authCookieOptions, maxAge: 0 });
    response.cookies.set(REFRESH_COOKIE, "", { ...authCookieOptions, maxAge: 0 });
    return response;
  }

  const account = (await accountResponse.json()) as Account;
  const response = NextResponse.json(account);
  if (renewed) {
    response.cookies.set(ACCESS_COOKIE, renewed.access_token, {
      ...authCookieOptions,
      maxAge: renewed.access_expires_in,
    });
    response.cookies.set(REFRESH_COOKIE, renewed.refresh_token, {
      ...authCookieOptions,
      maxAge: 60 * 60 * 24 * 30,
    });
  }
  return response;
}
