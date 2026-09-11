import "server-only";

import type { NextRequest } from "next/server";

/**
 * Same-origin check for CSRF defense on mutating auth/BFF routes.
 *
 * request.nextUrl.origin reflects the protocol Next.js's own server saw the
 * connection arrive on. Behind nginx (TLS terminated at the proxy, plain
 * HTTP from nginx to the frontend container) that's always "http", while a
 * real browser sends "Origin: https://...". Comparing against nextUrl.origin
 * directly makes every legitimate same-origin request behind TLS-terminating
 * nginx fail. Trust X-Forwarded-Proto/Host (nginx sets these) to reconstruct
 * the origin the browser actually saw.
 */
export function isTrustedOrigin(request: NextRequest): boolean {
  const origin = request.headers.get("origin");
  if (!origin) return true;
  const protocol = request.headers.get("x-forwarded-proto") || request.nextUrl.protocol.replace(":", "");
  const host = request.headers.get("host") || request.nextUrl.host;
  return origin === `${protocol}://${host}`;
}
