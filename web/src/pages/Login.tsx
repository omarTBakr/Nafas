import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { ApiError } from "../api";
import { useAuth } from "../auth";
import { useI18n } from "../i18n";

export default function Login() {
  const { t } = useI18n();
  const { login } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const me = await login(email, password);
      navigate(params.get("next") ?? (me.role === "doctor" ? "/doctor" : "/"), { replace: true });
    } catch (e) {
      setError(e instanceof ApiError && e.status === 401 ? t("wrongLogin") : t("error"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card stack auth" onSubmit={submit}>
      <h2>{t("login")}</h2>
      <label>
        {t("email")}
        <input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} dir="ltr" />
      </label>
      <label>
        {t("password")}
        <input
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </label>
      {error && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
      <button disabled={busy}>{t("login")}</button>
      <p className="small muted">
        {t("noAccount")} <Link to={`/register${params.get("next") ? `?next=${encodeURIComponent(params.get("next")!)}` : ""}`}>{t("register")}</Link>
      </p>
    </form>
  );
}
