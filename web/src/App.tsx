import { useEffect, useState, type ReactNode } from "react";
import { Navigate, NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";

import { api, type Role } from "./api";
import { useAuth } from "./auth";
import { useI18n } from "./i18n";
import Schedule from "./pages/doctor/Schedule";
import Home from "./pages/Home";
import Login from "./pages/Login";
import Appointments from "./pages/patient/Appointments";
import Book from "./pages/patient/Book";
import Notifications from "./pages/patient/Notifications";
import ProfilePage from "./pages/patient/Profile";
import Register from "./pages/Register";

/** Renders its page only for the right role; otherwise to login, remembering where to come back to. */
function RequireRole({ role, children }: { role: Role; children: ReactNode }) {
  const { me, ready } = useAuth();
  const location = useLocation();
  const { t } = useI18n();

  if (!ready) return <p className="muted">{t("loading")}</p>;
  if (!me) return <Navigate to={`/login?next=${encodeURIComponent(location.pathname)}`} replace />;
  if (me.role !== role) return <Navigate to={me.role === "doctor" ? "/doctor" : "/"} replace />;
  return <>{children}</>;
}

/** How many notices the patient has not dismissed, refreshed on each page change and every minute. */
function useUnread(enabled: boolean): number {
  const [count, setCount] = useState(0);
  const location = useLocation();
  useEffect(() => {
    if (!enabled) return;
    const load = () =>
      api
        .notifications(true)
        .then((n) => setCount(n.length))
        .catch(() => setCount(0));
    load();
    const timer = setInterval(load, 60_000);
    return () => clearInterval(timer);
  }, [enabled, location.pathname]);
  return enabled ? count : 0;
}

function TopBar() {
  const { me, logout } = useAuth();
  const { t, lang, setLang } = useI18n();
  const navigate = useNavigate();
  const unread = useUnread(me?.role === "patient");

  return (
    <header className="topbar">
      <div className="container">
        <NavLink to={me?.role === "doctor" ? "/doctor" : "/"} className="brand">
          <span className="brand-mark" aria-hidden="true">
            ◌
          </span>
          {t("brand")}
        </NavLink>
        <nav className="nav" aria-label="main">
          {me?.role === "doctor" ? (
            <NavLink to="/doctor">{t("schedule")}</NavLink>
          ) : (
            <>
              <NavLink to="/" end>
                {t("doctors")}
              </NavLink>
              {me?.role === "patient" && (
                <>
                  <NavLink to="/appointments">{t("myAppointments")}</NavLink>
                  <NavLink to="/notifications" className="bell">
                    {t("notifications")}
                    {unread > 0 && <span className="count">{unread}</span>}
                  </NavLink>
                  <NavLink to="/profile">{t("profile")}</NavLink>
                </>
              )}
            </>
          )}
          <button className="link" onClick={() => setLang(lang === "ar" ? "en" : "ar")} lang={lang === "ar" ? "en" : "ar"}>
            {lang === "ar" ? "English" : "العربية"}
          </button>
          {me ? (
            <button
              className="secondary"
              onClick={async () => {
                await logout();
                navigate("/");
              }}
            >
              {t("logout")}
            </button>
          ) : (
            <NavLink to="/login">{t("login")}</NavLink>
          )}
        </nav>
      </div>
    </header>
  );
}

export default function App() {
  return (
    <>
      <TopBar />
      <main className="container">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route
            path="/book/:doctorId"
            element={
              <RequireRole role="patient">
                <Book />
              </RequireRole>
            }
          />
          <Route
            path="/appointments"
            element={
              <RequireRole role="patient">
                <Appointments />
              </RequireRole>
            }
          />
          <Route
            path="/notifications"
            element={
              <RequireRole role="patient">
                <Notifications />
              </RequireRole>
            }
          />
          <Route
            path="/profile"
            element={
              <RequireRole role="patient">
                <ProfilePage />
              </RequireRole>
            }
          />
          <Route
            path="/doctor"
            element={
              <RequireRole role="doctor">
                <Schedule />
              </RequireRole>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </>
  );
}
