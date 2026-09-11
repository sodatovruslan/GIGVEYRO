import { type NextRequest, NextResponse } from "next/server";

import { ACCESS_COOKIE, authCookieOptions, backendFetch, REFRESH_COOKIE } from "@/lib/server/backend";
import { isTrustedOrigin } from "@/lib/server/origin";

export async function POST(request: NextRequest) {
  if (!isTrustedOrigin(request)) {
    return NextResponse.json({ detail: "Invalid request origin" }, { status: 403 });
  }

  const refreshToken = request.cookies.get(REFRESH_COOKIE)?.value;
  if (refreshToken) {
    try {
      await backendFetch("/auth/logout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
    } catch {
      // Best-effort: cookies are cleared below regardless, so the client
      // is logged out locally even if the backend call fails.
    }
  }

  const response = NextResponse.json({ ok: true });
  response.cookies.set(ACCESS_COOKIE, "", { ...authCookieOptions, maxAge: 0 });
  response.cookies.set(REFRESH_COOKIE, "", { ...authCookieOptions, maxAge: 0 });
  return response;
}
