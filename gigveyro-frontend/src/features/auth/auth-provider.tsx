"use client";

import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { ApiError, apiErrorFromPayload } from "@/lib/api/error";
import type { Account, LoginInput } from "@/lib/api/types";

type AuthStatus = "loading" | "authenticated" | "anonymous";
interface AuthContextValue {
  account: Account | null;
  status: AuthStatus;
  login: (input: LoginInput) => Promise<Account>;
  logout: () => Promise<void>;
  restoreSession: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [account, setAccount] = useState<Account | null>(null);
  const [status, setStatus] = useState<AuthStatus>("loading");

  const restoreSession = useCallback(async () => {
    try {
      const response = await fetch("/api/auth/session", { cache: "no-store" });
      if (!response.ok) {
        setAccount(null);
        setStatus("anonymous");
        return;
      }
      setAccount((await response.json()) as Account);
      setStatus("authenticated");
    } catch {
      setAccount(null);
      setStatus("anonymous");
    }
  }, []);

  useEffect(() => {
    let active = true;
    void fetch("/api/auth/session", { cache: "no-store" })
      .then(async (response) => {
        if (!active) return;
        if (!response.ok) {
          setAccount(null);
          setStatus("anonymous");
          return;
        }
        setAccount((await response.json()) as Account);
        setStatus("authenticated");
      })
      .catch(() => {
        if (active) {
          setAccount(null);
          setStatus("anonymous");
        }
      });
    return () => { active = false; };
  }, []);

  const login = useCallback(async (input: LoginInput) => {
    let response: Response;
    try {
      response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(input),
      });
    } catch {
      throw new ApiError(0, "Нет соединения с сервером.");
    }
    const payload = await response.json().catch(() => null) as unknown;
    if (!response.ok) throw apiErrorFromPayload(response.status, payload);
    const nextAccount = payload as Account;
    setAccount(nextAccount);
    setStatus("authenticated");
    return nextAccount;
  }, []);

  const logout = useCallback(async () => {
    await fetch("/api/auth/logout", { method: "POST" }).catch(() => null);
    setAccount(null);
    setStatus("anonymous");
  }, []);

  const value = useMemo(
    () => ({ account, status, login, logout, restoreSession }),
    [account, login, logout, restoreSession, status],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}
