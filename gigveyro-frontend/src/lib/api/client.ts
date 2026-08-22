import { ApiError, apiErrorFromPayload } from "@/lib/api/error";

type ApiInit = Omit<RequestInit, "body"> & { body?: unknown };
let apiGenerationController = new AbortController();

export function abortApiGeneration() {
  apiGenerationController.abort();
  apiGenerationController = new AbortController();
}

export async function apiFetch<T>(path: string, init: ApiInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  let body: BodyInit | undefined;
  if (init.body !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(init.body);
  }

  let response: Response;
  try {
    const signal = init.signal ? AbortSignal.any([init.signal, apiGenerationController.signal]) : apiGenerationController.signal;
    response = await fetch(`/api/backend${path.startsWith("/") ? path : `/${path}`}`, {
      ...init,
      body,
      headers,
      credentials: "same-origin",
      signal,
    });
  } catch {
    throw new ApiError(0, "Нет соединения с сервером.");
  }

  const contentLength = response.headers.get("content-length");
  const hasNoContent = response.status === 204 || init.method === "HEAD" || contentLength === "0";
  const payload = hasNoContent ? null : await response.json().catch(() => null);
  if (!response.ok) throw apiErrorFromPayload(response.status, payload);
  return payload as T;
}
