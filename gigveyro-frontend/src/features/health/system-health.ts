export type SystemHealthStatus = "checking" | "healthy" | "degraded" | "unavailable";

export function healthStatusFromPayload(
  responseOk: boolean,
  payload: unknown,
): Exclude<SystemHealthStatus, "checking"> {
  if (!responseOk) return "unavailable";
  if (!payload || typeof payload !== "object") return "degraded";
  const status = (payload as { status?: unknown }).status;
  if (status === "healthy") return "healthy";
  if (status === "unavailable") return "unavailable";
  return "degraded";
}
