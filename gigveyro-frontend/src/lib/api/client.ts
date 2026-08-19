import { ApiError, apiErrorFromPayload } from "@/lib/api/error";

type ApiInit = Omit<RequestInit, "body"> & { body?: unknown };

export async function apiFetch<T>(path: string, init: ApiInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  let body: BodyInit | undefined;
  if (init.body !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(init.body);
  }

  let response: Response;
  try {
    response = await fetch(`/api/backend${path.startsWith("/") ? path : `/${path}`}`, {
      ...init,
      body,
      headers,
      credentials: "same-origin",
    });
  } catch {
    throw new ApiError(0, "Нет соединения с сервером.");
  }

  const payload = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) throw apiErrorFromPayload(response.status, payload);
  return payload as T;
}
