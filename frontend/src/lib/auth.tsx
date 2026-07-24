"use client";

// Auth context: exposes user (from /api/auth/me), login, register, logout, loading.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  apiLogin,
  apiLogout,
  apiMe,
  apiRegister,
  type RegisterPayload,
} from "./api";
import {
  clearTokens,
  getAccess,
  getRefresh,
  setStoredSessionId,
  setTokens,
} from "./tokens";
import type { AuthUser } from "./types";

interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  login: (phone: string, password: string) => Promise<void>;
  register: (payload: RegisterPayload) => Promise<AuthUser>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const queryClient = useQueryClient();

  // Bootstrap: if a token exists, resolve the current user.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!getAccess()) {
        setLoading(false);
        return;
      }
      try {
        const me = await apiMe();
        if (!cancelled) setUser(me);
      } catch {
        if (!cancelled) setUser(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (phone: string, password: string) => {
    const pair = await apiLogin(phone, password);
    setTokens(pair.access_token, pair.refresh_token);
    const me = await apiMe();
    setUser(me);
  }, []);

  const register = useCallback(async (payload: RegisterPayload) => {
    return apiRegister(payload);
  }, []);

  const logout = useCallback(async () => {
    const refresh = getRefresh();
    if (refresh) await apiLogout(refresh);
    clearTokens();
    setStoredSessionId(null);
    setUser(null);
    queryClient.clear();
    if (typeof window !== "undefined") window.location.href = "/login";
  }, [queryClient]);

  const value = useMemo<AuthContextValue>(
    () => ({ user, loading, login, register, logout }),
    [user, loading, login, register, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within <AuthProvider>");
  return ctx;
}
