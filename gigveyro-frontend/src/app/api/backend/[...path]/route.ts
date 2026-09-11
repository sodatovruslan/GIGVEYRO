import { type NextRequest, NextResponse } from "next/server";

import {
  ACCESS_COOKIE,
  authCookieOptions,
  backendFetch,
  REFRESH_COOKIE,
  refreshTokens,
} from "@/lib/server/backend";
import { isTrustedOrigin } from "@/lib/server/origin";

interface RouteContext { params: Promise<{ path: string[] }> }

const requestHeaders = ["accept", "content-type", "idempotency-key"];
const responseHeaders = ["content-type", "content-disposition"];

async function forward(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  if (path[0] === "auth" && (path[1] === "login" || path[1] === "refresh")) {
    return NextResponse.json({ detail: "Route is not available through the API proxy" }, { status: 404 });
  }
  if (!["GET", "HEAD"].includes(request.method) && !isTrustedOrigin(request)) {
    return NextResponse.json({ detail: "Invalid request origin" }, { status: 403 });
  }
  const pathname = `/${path.map(encodeURIComponent).join("/")}${request.nextUrl.search}`;
  const refreshToken = request.cookies.get(REFRESH_COOKIE)?.value;
  let accessToken = request.cookies.get(ACCESS_COOKIE)?.value;
  let renewed = null;
  const body = request.method === "GET" || request.method === "HEAD" ? undefined : await request.arrayBuffer();

  const makeRequest = (token?: string) => {
    const headers = new Headers();
    for (const name of requestHeaders) {
      const value = request.headers.get(name);
      if (value) headers.set(name, value);
    }
    if (token) headers.set("Authorization", `Bearer ${token}`);
    return backendFetch(pathname, { method: request.method, headers, body });
  };

  let backendResponse: Response;
  try { backendResponse = await makeRequest(accessToken); }
  catch { return NextResponse.json({ detail: "Backend временно недоступен" }, { status: 502 }); }
  if (backendResponse.status === 401 && refreshToken) {
    renewed = await refreshTokens(refreshToken);
    if (renewed) {
      accessToken = renewed.access_token;
      try { backendResponse = await makeRequest(accessToken); }
      catch { return NextResponse.json({ detail: "Backend временно недоступен" }, { status: 502 }); }
    }
  }

  const headers = new Headers();
  for (const name of responseHeaders) {
    const value = backendResponse.headers.get(name);
    if (value) headers.set(name, value);
  }
  const contentLength = backendResponse.headers.get("content-length");
  const hasNoContent = backendResponse.status === 204 || request.method === "HEAD" || contentLength === "0";
  const response = new NextResponse(hasNoContent ? null : await backendResponse.arrayBuffer(), {
    status: backendResponse.status,
    headers,
  });
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

export const GET = forward;
export const POST = forward;
export const PATCH = forward;
export const PUT = forward;
export const DELETE = forward;
