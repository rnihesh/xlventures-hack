"use client";

// Client-side auth state. Wraps the app, fetches the current session from the
// backend on mount, and exposes login/logout helpers. Every request uses
// credentials:"include" so the httpOnly 'nba_session' cookie rides along.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import { API_BASE } from "@/lib/api";
import { authHeaders } from "@/lib/auth";

export interface AuthUser {
  id: string;
  email: string;
  name?: string | null;
  role?: string;
  org_id: string;
  email_verified?: boolean;
}

export interface AuthOrg {
  id: string;
  name: string;
}

export interface MeResponse {
  user: AuthUser;
  org: AuthOrg;
}

interface AuthContextValue {
  user: AuthUser | null;
  org: AuthOrg | null;
  loading: boolean;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [org, setOrg] = useState<AuthOrg | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/auth/me`, {
        headers: authHeaders({ Accept: "application/json" }),
        credentials: "include",
        cache: "no-store",
      });
      if (!res.ok) {
        setUser(null);
        setOrg(null);
        return;
      }
      const data = (await res.json()) as MeResponse;
      setUser(data.user ?? null);
      setOrg(data.org ?? null);
    } catch {
      // Backend unreachable: treat as signed out without crashing the shell.
      setUser(null);
      setOrg(null);
    } finally {
      setLoading(false);
    }
  }, []);

  const logout = useCallback(async () => {
    try {
      await fetch(`${API_BASE}/auth/logout`, {
        method: "POST",
        headers: authHeaders(),
        credentials: "include",
      });
    } catch {
      // best effort: clear local state regardless
    }
    setUser(null);
    setOrg(null);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <AuthContext.Provider value={{ user, org, loading, refresh, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}
