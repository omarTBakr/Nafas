import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, type Doctor, type Specialization } from "../api";
import { useAuth } from "../auth";
import { useI18n } from "../i18n";

export default function Home() {
  const { t, lang } = useI18n();
  const { me } = useAuth();
  const [specializations, setSpecializations] = useState<Specialization[]>([]);
  const [chosen, setChosen] = useState<string | undefined>();
  const [doctors, setDoctors] = useState<Doctor[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    api.specializations().then(setSpecializations).catch(() => setFailed(true));
  }, []);

  useEffect(() => {
    setDoctors(null);
    api
      .doctors(chosen)
      .then(setDoctors)
      .catch(() => setFailed(true));
  }, [chosen]);

  const name = (d: Doctor) => (lang === "ar" ? d.full_name_ar : d.full_name_en);
  const specialty = (d: Doctor) => (lang === "ar" ? d.specialization_ar : d.specialization_en);

  return (
    <div className="stack">
      <section className="hero">
        <h1>{t("findDoctor")}</h1>
        <p>{t("tagline")}</p>
      </section>

      <div className="chips" role="group" aria-label={t("allSpecializations")}>
        <button className="chip" aria-pressed={chosen === undefined} onClick={() => setChosen(undefined)}>
          {t("allSpecializations")}
        </button>
        {specializations.map((s) => (
          <button key={s.code} className="chip" aria-pressed={chosen === s.code} onClick={() => setChosen(s.code)}>
            {lang === "ar" ? s.name_ar : s.name_en}
          </button>
        ))}
      </div>

      {failed && <p className="notice error">{t("error")}</p>}
      {doctors === null && !failed && <p className="muted">{t("loading")}</p>}

      <div className="grid-cards">
        {doctors?.map((d) => (
          <article key={d.doctor_id} className="card doctor-card">
            <div className="row">
              <div className="avatar" aria-hidden="true">
                {name(d).replace(/^(د\.|Dr\.?)\s*/, "").charAt(0)}
              </div>
              <div>
                <h3 style={{ marginBlock: 0 }}>{name(d)}</h3>
                <div className="muted small">{specialty(d)}</div>
              </div>
            </div>
            <Link
              className="button"
              to={me?.role === "patient" || !me ? `/book/${d.doctor_id}` : "/doctor"}
              aria-label={`${t("book")} — ${name(d)}`}
            >
              {t("book")}
            </Link>
          </article>
        ))}
      </div>
    </div>
  );
}
