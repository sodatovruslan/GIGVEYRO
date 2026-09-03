import { apiFetch } from "@/lib/api/client";
import type {
  AuthSessionListResponse,
  LogoutAllResult,
  TwoFactorRegenerateResult,
  TwoFactorSetupConfirmResult,
  TwoFactorSetupStart,
  TwoFactorStatus,
} from "@/lib/api/types";

export const securityApi = {
  status: () => apiFetch<TwoFactorStatus>("/auth/2fa/status"),
  setupStart: (password: string) =>
    apiFetch<TwoFactorSetupStart>("/auth/2fa/setup/start", { method: "POST", body: { password } }),
  setupConfirm: (totpCode: string) =>
    apiFetch<TwoFactorSetupConfirmResult>("/auth/2fa/setup/confirm", {
      method: "POST",
      body: { totp_code: totpCode },
    }),
  disable: (password: string, code: string) =>
    apiFetch<void>("/auth/2fa/disable", { method: "POST", body: { password, code } }),
  regenerateRecoveryCodes: (password: string, totpCode: string) =>
    apiFetch<TwoFactorRegenerateResult>("/auth/2fa/recovery/regenerate", {
      method: "POST",
      body: { password, totp_code: totpCode },
    }),
  sessions: () => apiFetch<AuthSessionListResponse>("/auth/sessions"),
  revokeSession: (sessionId: string) =>
    apiFetch<void>(`/auth/sessions/${sessionId}`, { method: "DELETE" }),
  logoutAll: () => apiFetch<LogoutAllResult>("/auth/logout-all", { method: "POST" }),
  changePassword: (currentPassword: string, newPassword: string, code?: string) =>
    apiFetch<void>("/auth/password/change", {
      method: "POST",
      body: {
        current_password: currentPassword,
        new_password: newPassword,
        code: code || null,
      },
    }),
};
