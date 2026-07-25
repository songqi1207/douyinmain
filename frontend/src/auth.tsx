import { createContext, useContext, useEffect, useMemo, useState } from "react";

import { fetchMe, logout as apiLogout } from "./api";
import type { AuthState } from "./api";

type AuthContextValue = AuthState & {
  loading: boolean;
  refresh: () => Promise<AuthState>;
  setAuth: (state: AuthState) => void;
  logout: () => Promise<void>;
};

const EMPTY_AUTH: AuthState = {
  user: null,
  workflow_favorites: [],
  voice_favorites: [],
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [auth, setAuth] = useState<AuthState>(EMPTY_AUTH);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    const next = await fetchMe();
    setAuth(next);
    return next;
  }

  useEffect(() => {
    refresh().catch(() => setAuth(EMPTY_AUTH)).finally(() => setLoading(false));
  }, []);

  async function logout() {
    await apiLogout();
    setAuth(EMPTY_AUTH);
  }

  const value = useMemo(
    () => ({ ...auth, loading, refresh, setAuth, logout }),
    [auth, loading],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}
