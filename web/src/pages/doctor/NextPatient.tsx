import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, type NextPatient as NextPatientData } from "../../api";
import { useI18n } from "../../i18n";
import { clinicClock, clinicDay } from "../../time";

/** Who is next today, and what to know before they walk in. */
export default function NextPatient() {
  const { t, locale } = useI18n();
  const [next, setNext] = useState<NextPatientData | null>(null);

  useEffect(() => {
    const load = () =>
      api
        .nextPatient()
        .then(setNext)
        .catch(() => setNext(null));
    load();
    const timer = setInterval(load, 60_000);
    return () => clearInterval(timer);
  }, []);

  if (!next) return null;
  if (!next.appointment || !next.patient || !next.brief)
    return (
      <section className="card">
        <h3 style={{ marginBlock: 0 }}>{t("nextPatient")}</h3>
        <p className="muted small">{t("noNextPatient")}</p>
      </section>
    );

  const tz = next.timezone;
  const { brief } = next;
  return (
    <section className="card stack next-patient">
      <div className="row spread">
        <h3 style={{ marginBlock: 0 }}>
          {t("nextPatient")}: {next.patient.full_name}
        </h3>
        <span className="time">{clinicClock(next.appointment.start, tz, locale)}</span>
      </div>
      {next.appointment.reason_for_visit && <p className="muted">{next.appointment.reason_for_visit}</p>}
      <ul className="small">
        <li>
          {t("lastVisit")}: {brief.last_visit ? clinicDay(brief.last_visit, tz, locale) : t("firstVisit")}
        </li>
        <li>
          {t("documentsOnFile")}: {brief.documents}
        </li>
        {brief.open_questions.length > 0 && (
          <li className="notice warn">
            {t("openQuestions")}: {brief.open_questions.length}
          </li>
        )}
        {brief.recent_entries.map((e) => (
          <li key={e.entry_id}>{e.content}</li>
        ))}
      </ul>
      <div>
        <Link className="button secondary" to={`/doctor/patients/${next.patient.patient_id}`}>
          {t("openPatient")}
        </Link>
      </div>
    </section>
  );
}
