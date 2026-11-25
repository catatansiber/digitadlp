import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import type { Me } from "../api/types";
import { onSessionExpired } from "./sessionEvents";

export const SESSION_EXPIRED = "Sesi berakhir. Silakan masuk lagi.";

type AuthValue = {
  user: Me | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<Me>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();
  const location = useLocation();
  const qc = useQueryClient();

  useEffect(() => {
    let alive = true;
    api<Me>("/auth/me")
      .then((me) => alive && setUser(me))
      .catch(() => alive && setUser(null))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, []);

  const here = location.pathname + location.search;
  useEffect(
    () =>
      onSessionExpired(() => {
        setUser(null);
        qc.clear();
        if (location.pathname === "/masuk") return;
        navigate(`/masuk?kembali=${encodeURIComponent(here)}`, { replace: true, state: { expired: true } });
      }),
    [here, location.pathname, navigate, qc],
  );

  const login = useCallback(async (username: string, password: string) => {
    const me = await api<Me>("/auth/login", { method: "POST", body: JSON.stringify({ username, password }) });
    setUser(me);
    return me;
  }, []);

  const logout = useCallback(async () => {
    try {
      await api("/auth/logout", { method: "POST" });
    } catch (e) {
      if (!(e instanceof ApiError)) throw e;
    }
    setUser(null);
    qc.clear();
    navigate("/masuk", { replace: true });
  }, [navigate, qc]);

  const value = useMemo(() => ({ user, loading, login, logout }), [user, loading, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const v = useContext(AuthContext);
  if (!v) throw new Error("useAuth harus di dalam AuthProvider");
  return v;
}
