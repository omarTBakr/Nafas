import { useEffect, useState, type FormEvent } from "react";

import { api, DIALECTS, type Profile, type SpokenDialect, type VoiceGender } from "../../api";
import { useI18n } from "../../i18n";

export default function ProfilePage() {
  const { t } = useI18n();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [dialect, setDialect] = useState<SpokenDialect | "">("");
  const [voice, setVoice] = useState<VoiceGender | "">("");
  const [state, setState] = useState<"idle" | "saving" | "saved" | "error">("idle");

  useEffect(() => {
    api
      .profile()
      .then((p) => {
        setProfile(p);
        setDialect(p.dialect ?? "");
        setVoice(p.voice ?? "");
      })
      .catch(() => setState("error"));
  }, []);

  async function save(event: FormEvent) {
    event.preventDefault();
    setState("saving");
    try {
      setProfile(await api.updateProfile({ dialect: dialect || null, voice: voice || null }));
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
    </form>
  );
}
