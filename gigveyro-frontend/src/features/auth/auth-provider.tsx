"use client";

import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

import { AuthOperationGate } from "@/features/auth/auth-operation-gate";
import { ApiError, apiErrorFromPayload } from "@/lib/api/error";
import { abortApiGeneration } from "@/lib/api/client";
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
  const gateRef = useRef(new AuthOperationGate());

  const restoreSession = useCallback(async () => {
    const { id: operation, controller } = gateRef.current.startSession();
    try {
      const response = await fetch("/api/auth/session", { cache: "no-store", signal: controller.signal });
      if (!gateRef.current.isCurrent(operation)) return;
      if (!response.ok) {
        setAccount(null);
        setStatus("anonymous");
        return;
      }
      setAccount((await response.json()) as Account);
      setStatus("authenticated");
    } catch {
      if (controller.signal.aborted || !gateRef.current.isCurrent(operation)) return;
      setAccount(null);
      setStatus("anonymous");
    } finally {
      gateRef.current.finishSession(controller);
    }
  }, []);

  useEffect(() => {
    const gate = gateRef.current;
    const timeoutId = window.setTimeout(() => void restoreSession(), 0);
    return () => {
      window.clearTimeout(timeoutId);
      gate.cancel();
    };
  }, [restoreSession]);

  const login = useCallback(async (input: LoginInput) => {
    const operation = gateRef.current.startExclusive();
    abortApiGeneration();
    let response: Response;
    try {
      response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(input),
        cache: "no-store",
      });
    } catch {
      throw new ApiError(0, "Connection failed");
    }
    const payload = await response.json().catch(() => null) as unknown;
    if (!gateRef.current.isCurrent(operation)) throw new ApiError(409, "Authentication request was superseded");
    if (!response.ok) throw apiErrorFromPayload(response.status, payload);
    const nextAccount = payload as Account;
    setAccount(nextAccount);
    setStatus("authenticated");
    return nextAccount;
  }, []);

  const logout = useCallback(async () => {
    gateRef.current.startExclusive();
    abortApiGeneration();
    setAccount(null);
    setStatus("anonymous");
    await fetch("/api/auth/logout", { method: "POST", cache: "no-store" }).catch(() => null);
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
