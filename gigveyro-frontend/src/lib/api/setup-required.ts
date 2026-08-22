import { apiErrorFromPayload } from "@/lib/api/error";
import type { TwoFactorSetupStart } from "@/lib/api/types";

// Plain fetch (not apiFetch/client.ts): this call carries a short-lived
// setup_token explicitly, not the session cookie apiFetch relies on - there
// is no session yet during forced OWNER 2FA onboarding.
export async function startForcedTwoFactorSetup(setupToken: string): Promise<TwoFactorSetupStart> {
  let response: Response;
  try {
    response = await fetch("/api/auth/2fa/setup-required/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ setup_token: setupToken }),
      cache: "no-store",
    });
  } catch {
    throw apiErrorFromPayload(0, null);
  }
  const payload = await response.json().catch(() => null);
  if (!response.ok) throw apiErrorFromPayload(response.status, payload);
  return payload as TwoFactorSetupStart;
}
