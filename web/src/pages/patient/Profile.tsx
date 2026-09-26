import { useEffect, useState, type FormEvent } from "react";

import { api, DIALECTS, type Consent, type Doctor, type Profile, type SpokenDialect, type VoiceGender } from "../../api";
import { useI18n } from "../../i18n";

export default function ProfilePage() {
  const { t, lang } = useI18n();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [dialect, setDialect] = useState<SpokenDialect | "">("");
  const [voice, setVoice] = useState<VoiceGender | "">("");
  const [emailNotices, setEmailNotices] = useState(true);
  const [state, setState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [suggested, setSuggested] = useState<SpokenDialect | null>(null);
  const [consents, setConsents] = useState<Consent[]>([]);
  const [doctors, setDoctors] = useState<Doctor[]>([]);

  const loadConsents = () =>
    api
      .consents()
      .then(setConsents)
      .catch(() => setConsents([]));

  useEffect(() => {
    api
      .profile()
      .then((p) => {
        setProfile(p);
        setDialect(p.dialect ?? "");
        setVoice(p.voice ?? "");
        setEmailNotices(p.email_notices);
      })
      .catch(() => setState("error"));
    // a suggestion from what the patient has written; offered, never applied by itself
    api
      .dialectSuggestion()
      .then((s) => setSuggested(s.dialect))
      .catch(() => setSuggested(null));
    loadConsents();
    api
      .doctors()
      .then(setDoctors)
      .catch(() => setDoctors([]));
  }, []);

  async function save(event: FormEvent) {
    event.preventDefault();
    setState("saving");
    try {
      setProfile(await api.updateProfile({ dialect: dialect || null, voice: voice || null, email_notices: emailNotices }));
      setState("saved");
    } catch {
      setState("error");
    }
  }

  if (!profile) return state === "error" ? <p className="notice error">{t("error")}</p> : <p className="muted">{t("loading")}</p>;

  return (
    <form className="card stack auth" onSubmit={save}>
      <h2>{profile.full_name}</h2>

      <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0 }}>
        <legend style={{ fontWeight: 600 }}>{t("dialect")}</legend>
        <p className="hint">{t("dialectHint")}</p>
        {suggested && !profile.dialect && dialect === "" && (
          <p className="notice info row spread">
            <span>
              {t("suggestedDialect")} {t(`dialect_${suggested}`)}
            </span>
            <button type="button" className="secondary" onClick={() => setDialect(suggested)}>
              {t("useSuggestion")}
            </button>
          </p>
        )}
        <div className="chips">
          {DIALECTS.map((d) => (
            <button key={d} type="button" className="chip" aria-pressed={dialect === d} onClick={() => setDialect(d)}>
              {t(`dialect_${d}`)}
            </button>
          ))}
        </div>
      </fieldset>

      <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0 }}>
        <legend style={{ fontWeight: 600 }}>{t("voice")}</legend>
        <div className="chips">
          {(["", "female", "male"] as const).map((v) => (
            <button key={v || "any"} type="button" className="chip" aria-pressed={voice === v} onClick={() => setVoice(v)}>
              {v ? t(`voice_${v}`) : t("voiceAny")}
            </button>
          ))}
        </div>
      </fieldset>

      <label className="consent">
        <input type="checkbox" checked={emailNotices} onChange={(e) => setEmailNotices(e.target.checked)} />
        <span>{t("emailNotices")}</span>
      </label>

      {state === "saved" && (
        <p className="notice ok" role="status">
          {t("saved")}
        </p>
      )}
      {state === "error" && (
        <p className="notice error" role="alert">
          {t("error")}
        </p>
      )}
      <button disabled={state === "saving"}>{t("save")}</button>

      <section className="stack" aria-label={t("consents")}>
        <h3>{t("consents")}</h3>
        <p className="hint">{t("revokeHint")}</p>
        {consents.map((c) => {
          const doctor = doctors.find((d) => d.doctor_id === c.doctor_id);
          return (
            <div key={c.consent_id} className="row spread">
              <span>
                {t(`consent_${c.kind}`)}
                {doctor && ` · ${lang === "ar" ? doctor.full_name_ar : doctor.full_name_en}`}
              </span>
              <button
                type="button"
                className="secondary"
                onClick={async () => {
                  await api.revokeConsent(c.consent_id);
                  loadConsents();
                }}
              >
                {t("revoke")}
              </button>
            </div>
          );
        })}
      </section>
    </form>
  );
}
