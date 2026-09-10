import React, { createContext, useContext, useMemo, useState } from "react";
import { api, clearSession, getStoredUser, getToken, storeSession } from "./client";

interface AuthCtx {
  user: any | null;
  token: string | null;
  login: (username: string, password: string) => Promise<any>;
  logout: () => void;
  refresh: () => Promise<void>;
}

const Ctx = createContext<AuthCtx>({
  user: null,
  token: null,
  login: async () => undefined,
  logout: () => {},
  refresh: async () => {},
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<any | null>(getStoredUser());

  const login = async (username: string, password: string) => {
    const data = await api.post("/auth/login", { username, password });
    storeSession(data.token, data.user);
    setUser(data.user);
    return data.user;
  };

  const logout = () => {
    clearSession();
    setUser(null);
  };

  const refresh = async () => {
    const data = await api.get("/auth/me");
    storeSession(getToken() || "", data);
    setUser(data);
  };

  const value = useMemo(
    () => ({ user, token: getToken(), login, logout, refresh }),
    [user]
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth() {
  return useContext(Ctx);
}
