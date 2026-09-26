import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, type Appointment } from "../../api";
import { useI18n } from "../../i18n";
import { clinicClock, clinicDay } from "../../time";
import { joinable } from "../../visit";

const ACTIVE = new Set(["held", "confirmed"]);

export default function Appointments() {
  const { t, lang, locale } = useI18n();
  const [appointments, setAppointments] = useState<Appointment[] | null>(null);
  const [failed, setFailed] = useState(false);

  const load = useCallback(() => {
    api
      .mine()
      .then(setAppointments)
      .catch(() => setFailed(true));
  }, []);

  useEffect(load, [load]);

  async function cancel(a: Appointment) {
    await api.cancel(a.appointment_id);
    load();
  }

  if (failed) return <p className="notice error">{t("error")}</p>;
  if (!appointments) return <p className="muted">{t("loading")}</p>;

  const now = Date.now();
  const upcoming = appointments.filter((a) => new Date(a.end).getTime() > now);
  const past = appointments.filter((a) => new Date(a.end).getTime() <= now).reverse();

  const render = (a: Appointment) => {
    const tz = a.timezone ?? "Africa/Cairo";
    const name = a.doctor ? (lang === "ar" ? a.doctor.full_name_ar : a.doctor.full_name_en) : "";
    const canCancel = ACTIVE.has(a.status) && new Date(a.start).getTime() > now;
    return (
      <article key={a.appointment_id} className="card appointment">
        <div className="row spread">
          <strong>{name}</strong>
          <span className={`badge ${a.status}`}>{t(`status_${a.status}`)}</span>
        </div>
        <span className="time">
          {clinicDay(a.start, tz, locale)} · {clinicClock(a.start, tz, locale)}
        </span>
        {a.reason_for_visit && <span className="muted small">{a.reason_for_visit}</span>}
        {a.mode === "online" && a.status === "confirmed" && (
          <div className="row">
            <span className="badge">{t("onlineVisit")}</span>
            {joinable(a) && (
              <Link className="button" to={`/visit/${a.appointment_id}`}>
                {t("joinOnline")}
              </Link>
            )}
          </div>
        )}
        {canCancel && (
          <div>
            <button className="danger" onClick={() => cancel(a)}>
              {t("cancelAppointment")}
            </button>
          </div>
        )}
      </article>
    );
  };

  return (
    <div className="stack">
      <h1>{t("myAppointments")}</h1>
      {appointments.length === 0 && (
        <div className="card stack">
          <p className="muted">{t("noAppointments")}</p>
          <div>
            <Link className="button" to="/">
              {t("book")}
            </Link>
          </div>
        </div>
      )}
      {upcoming.map(render)}
      {past.length > 0 && <div className="stack">{past.map(render)}</div>}
    </div>
  );
}
