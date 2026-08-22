import { type NextRequest, NextResponse } from "next/server";

import type { TwoFactorSetupStart } from "@/lib/api/types";
import { backendFetch } from "@/lib/server/backend";

interface StartInput { setup_token: string }

// Dedicated route (not the generic /api/backend proxy): the caller has no
// session cookie yet at this point (OWNER_2FA_REQUIRED forced onboarding,
// right after login) - only a short-lived setup_token held in page state.
// The token is forwarded as a bearer credential directly to the backend,
// which accepts it only for the onboarding setup/confirm endpoints (see
// backend api/deps.py:get_two_factor_setup_actor) - it grants no other API
// access, so passing it through server-side here carries the same risk
// profile as the existing 2FA challenge_token flow.
export async function POST(request: NextRequest) {
  const origin = request.headers.get("origin");
  if (origin && origin !== request.nextUrl.origin) {
    return NextResponse.json({ detail: "Invalid request origin" }, { status: 403 });
  }
  const payload = (await request.json().catch(() => null)) as StartInput | null;
  if (!payload?.setup_token) {
    return NextResponse.json({ detail: "Missing setup token" }, { status: 400 });
  }

  let response: Response;
  try {
    response = await backendFetch("/auth/2fa/setup/start", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${payload.setup_token}`,
      },
      body: JSON.stringify({}),
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

  const body = (await response.json()) as TwoFactorSetupStart;
  return NextResponse.json(body);
}
