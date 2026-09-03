import { NextResponse } from "next/server";

import { backendFetch } from "@/lib/server/backend";

export async function GET() {
  try {
    const response = await backendFetch("/health/ready", {
      method: "GET",
      signal: AbortSignal.timeout(5_000),
    });
    const payload = await response.json().catch(() => null) as { status?: unknown } | null;
    if (!response.ok) {
      return NextResponse.json({ status: "unavailable" }, { status: 503 });
    }
    return NextResponse.json({ status: payload?.status === "ready" ? "healthy" : "degraded" });
  } catch {
    return NextResponse.json({ status: "unavailable" }, { status: 503 });
  }
}
