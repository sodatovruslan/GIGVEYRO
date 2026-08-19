import { type NextRequest, NextResponse } from "next/server";

import { ACCESS_COOKIE, authCookieOptions, REFRESH_COOKIE } from "@/lib/server/backend";

export async function POST(request: NextRequest) {
  const origin = request.headers.get("origin");
  if (origin && origin !== request.nextUrl.origin) {
    return NextResponse.json({ detail: "Invalid request origin" }, { status: 403 });
  }
  const response = NextResponse.json({ ok: true });
  response.cookies.set(ACCESS_COOKIE, "", { ...authCookieOptions, maxAge: 0 });
  response.cookies.set(REFRESH_COOKIE, "", { ...authCookieOptions, maxAge: 0 });
  return response;
}
