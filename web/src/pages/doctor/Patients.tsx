import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, type PatientCard } from "../../api";
import { useI18n } from "../../i18n";

export default function Patients() {
  const { t, locale } = useI18n();
  const [patients, setPatients] = useState<PatientCard[] | null>(null);
  const [failed, setFailed] = useState(false);

  const load = useCallback(() => {
    setFailed(false);
    api
      .patients()
      .then((result) => {
        setPatients(result);
        setFailed(false);
      })
      .catch(() => setFailed(true));
  }, []);

  useEffect(load, [load]);

  if (failed)
    return (
      <div className="stack">
        <p className="notice error" role="alert">
          {t("error")}
        </p>
        <div>
          <button className="secondary" onClick={load}>
            {t("tryAgain")}
          </button>
        </div>
      </div>
    );
  if (!patients) return <p className="muted">{t("loading")}</p>;
  return (
    <div className="stack">
      <h1>{t("patients")}</h1>
      {patients.length === 0 && <p className="muted">{t("noPatients")}</p>}
      {patients.map((p) => (
        <Link key={p.patient_id} to={`/doctor/patients/${p.patient_id}`} className="card row spread patient-row">
          <strong>{p.full_name}</strong>
          <span className="muted small">
            {t("firstVisit")} {new Intl.DateTimeFormat(locale, { dateStyle: "medium" }).format(new Date(p.first_seen_at))}
          </span>
        </Link>
      ))}
    </div>
  );
}
