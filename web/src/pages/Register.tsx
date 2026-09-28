import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { ApiError, DIALECTS, type SpokenDialect } from "../api";
import { useAuth } from "../auth";
import { useI18n, type Lang } from "../i18n";

export default function Register() {
  const { t, lang } = useI18n();
  const { register } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [form, setForm] = useState({
    full_name: "",
    email: "",
    password: "",
    phone: "",
    preferred_language: lang as Lang,
    dialect: "" as SpokenDialect | "",
  });
  const [consented, setConsented] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const set = (field: keyof typeof form) => (event: { target: { value: string } }) =>
    setForm({ ...form, [field]: event.target.value });

  function explain(e: unknown): string {
    if (!(e instanceof ApiError)) return t("error");
    if (e.status === 409) return t("emailTaken");
    // a validation failure names its field; say which, in the reader's language
    if (e.status === 422) {
      if (e.fields.email) return t("invalidEmail");
      if (e.fields.password) return t("invalidPassword");
      return t("invalidForm");
    }
    return t("error");
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await register({ ...form, phone: form.phone || undefined, dialect: form.dialect || undefined, accept_data_processing: true });
      navigate(params.get("next") ?? "/", { replace: true });
    } catch (e) {
      setError(explain(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card stack auth" onSubmit={submit}>
      <h2>{t("register")}</h2>
      <label>
        {t("fullName")}
        <input required minLength={2} autoComplete="name" value={form.full_name} onChange={set("full_name")} />
      </label>
      <label>
        {t("email")}
        <input type="email" required autoComplete="email" value={form.email} onChange={set("email")} dir="ltr" />
      </label>
      <label>
        {t("password")} <span className="hint">{t("passwordHint")}</span>
        <input type="password" required minLength={12} autoComplete="new-password" value={form.password} onChange={set("password")} />
      </label>
      <label>
        {t("phone")}
        <input type="tel" autoComplete="tel" value={form.phone} onChange={set("phone")} dir="ltr" />
      </label>
      <label>
        {t("preferredLanguage")}
        <select value={form.preferred_language} onChange={set("preferred_language")}>
          <option value="ar">العربية</option>
          <option value="en">English</option>
        </select>
      </label>
      <label>
        {t("dialect")} <span className="hint">{t("dialectHint")}</span>
        <select value={form.dialect} onChange={set("dialect")}>
          <option value="">{t("chooseDialect")}</option>
          {DIALECTS.map((d) => (
            <option key={d} value={d}>
              {t(`dialect_${d}`)}
            </option>
          ))}
        </select>
      </label>
      <label className="consent">
        <input type="checkbox" required checked={consented} onChange={(e) => setConsented(e.target.checked)} />
        <span>{t("consentDataProcessing")}</span>
      </label>
      {error && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
      <button disabled={busy || !consented}>{t("register")}</button>
      <p className="small muted">
        {t("doctorAccountHint")} <Link to="/login">{t("doctorLogin")}</Link>
      </p>
      <p className="small muted">
        {t("haveAccount")} <Link to={`/login${params.get("next") ? `?next=${encodeURIComponent(params.get("next")!)}` : ""}`}>{t("login")}</Link>
      </p>
    </form>
  );
}
