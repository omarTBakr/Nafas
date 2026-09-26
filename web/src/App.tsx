import type { ReactNode } from "react";
import { Navigate, NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";

import type { Role } from "./api";
import { useAuth } from "./auth";
import { useI18n } from "./i18n";
import Schedule from "./pages/doctor/Schedule";
import Home from "./pages/Home";
import Login from "./pages/Login";
import Appointments from "./pages/patient/Appointments";
import Book from "./pages/patient/Book";
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

function TopBar() {
  const { me, logout } = useAuth();
  const { t, lang, setLang } = useI18n();
  const navigate = useNavigate();

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
              {me?.role === "patient" && <NavLink to="/appointments">{t("myAppointments")}</NavLink>}
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
