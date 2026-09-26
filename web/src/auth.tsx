import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { api, ApiError, type Me } from "./api";

interface Auth {
  me: Me | null;
  ready: boolean;
  login: (email: string, password: string) => Promise<Me>;
  register: (form: Parameters<typeof api.register>[0]) => Promise<Me>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<Auth | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    // the session is an httpOnly cookie: the only way to know who we are is to ask
    api
      .me()
      .then(setMe)
      .catch((e) => {
        if (!(e instanceof ApiError && e.status === 401)) console.error(e);
      })
      .finally(() => setReady(true));
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const account = await api.login(email, password);
    setMe(account);
    return account;
  }, []);

  const register = useCallback(async (form: Parameters<typeof api.register>[0]) => {
    const account = await api.register(form);
    setMe(account);
    return account;
  }, []);

  const logout = useCallback(async () => {
    await api.logout();
    setMe(null);
  }, []);

  return <AuthContext.Provider value={{ me, ready, login, register, logout }}>{children}</AuthContext.Provider>;
}

export function useAuth(): Auth {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth outside AuthProvider");
  return context;
}
