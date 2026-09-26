import { render } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

import { AuthProvider } from "./auth";
import { I18nProvider } from "./i18n";

export type Handler = (init: RequestInit | undefined, url: string) => unknown;

export function json(body: unknown, status = 200) {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/**
 * fetch answered by `routes`, keyed "METHOD /path" (the query string ignored).
 * A handler returns a Response, or a body for a 200. Unknown routes are 404,
 * and /api/auth/me is 401 unless given. Every call is recorded.
 */
export function stubFetch(routes: Record<string, Handler>) {
  const calls: { method: string; url: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const path = url.split("?")[0];
      const body = init?.body && typeof init.body === "string" ? JSON.parse(init.body) : undefined;
      calls.push({ method, url, body });
      const handler = routes[`${method} ${path}`];
      if (!handler) return path === "/api/auth/me" ? json({ detail: "not logged in" }, 401) : json({}, 404);
      const answer = handler(init, url);
      return answer instanceof Response ? answer : json(answer);
    }),
  );
  return calls;
}

function Where() {
  const location = useLocation();
  return <output data-testid="where">{location.pathname}</output>;
}

/** The page at `path` (a route pattern) opened at `at`, in English, with the session and the router. */
export function renderPage(page: ReactNode, { path = "/", at = path }: { path?: string; at?: string } = {}) {
  localStorage.setItem("nafas.lang", "en");
  return render(
    <I18nProvider>
      <AuthProvider>
        <MemoryRouter initialEntries={[at]}>
          <Routes>
            <Route path={path} element={page} />
            <Route path="*" element={<Where />} />
          </Routes>
          <Where />
        </MemoryRouter>
      </AuthProvider>
    </I18nProvider>,
  );
}
