export function loginErrorKey(reason: unknown) {
  if (reason && typeof reason === "object" && "status" in reason && reason.status === 401) {
    return "invalidCredentials" as const;
  }
  return null;
}
