import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { api, ApiError, type Me } from "./api";

interface Auth {
  me: Me | null;
  ready: boolean;
  // the server could not be reached to ask who we are: not the same as logged out
  unreachable: boolean;
  login: (email: string, password: string) => Promise<Me>;
  register: (form: Parameters<typeof api.register>[0]) => Promise<Me>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<Auth | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [ready, setReady] = useState(false);
  const [unreachable, setUnreachable] = useState(false);

  useEffect(() => {
    // The session is an httpOnly cookie: the only way to know who we are is to
    // ask. Only a 401 means "logged out". Anything else (a 502 while a
    // container restarts, a dropped connection) is retried with a growing
    // pause, and never treated as a logout: that sent a doctor to the login
    // page in the middle of their work.
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const ask = (attempt: number) => {
      api
        .me()
        .then((account) => {
          if (cancelled) return;
          setMe(account);
          setUnreachable(false);
          setReady(true);
        })
        .catch((e) => {
          if (cancelled) return;
          if (e instanceof ApiError && e.status === 401) {
            setMe(null);
            setUnreachable(false);
            setReady(true);
            return;
          }
          console.error(e);
          if (attempt >= 2) {
            setUnreachable(true);
            setReady(true);
          }
          timer = setTimeout(() => ask(attempt + 1), Math.min(500 * 2 ** attempt, 10_000));
        });
    };
    ask(0);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
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
    try {
      await api.logout();
    } finally {
      // this browser forgets the session whether or not the server answered
      setMe(null);
    }
  }, []);

  return (
    <AuthContext.Provider value={{ me, ready, unreachable, login, register, logout }}>{children}</AuthContext.Provider>
  );
}

export function useAuth(): Auth {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth outside AuthProvider");
  return context;
}
