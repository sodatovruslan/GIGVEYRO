import { NextResponse } from "next/server";

import { ACCESS_COOKIE, authCookieOptions, REFRESH_COOKIE } from "@/lib/server/backend";

export async function POST() {
  const response = NextResponse.json({ ok: true });
  response.cookies.set(ACCESS_COOKIE, "", { ...authCookieOptions, maxAge: 0 });
  response.cookies.set(REFRESH_COOKIE, "", { ...authCookieOptions, maxAge: 0 });
  return response;
}
