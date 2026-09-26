import { useCallback, useEffect, useState } from "react";

import { api, type Appointment, type Schedule as ScheduleData } from "../../api";
import { useI18n } from "../../i18n";
import { clinicClock, clinicDate, clinicDay, upcomingDates } from "../../time";
import NextPatient from "./NextPatient";

type Range = "today" | "week";

export default function Schedule() {
  const { t, locale } = useI18n();
  const [range, setRange] = useState<Range>("today");
  const [data, setData] = useState<ScheduleData | null>(null);
  const [failed, setFailed] = useState(false);

  const load = useCallback(() => {
    // the clinic's zone arrives with the answer, so ask for a margin either
    // side and cut the days out in clinic time below
    const start = new Date(Date.now() - 24 * 3600 * 1000);
    const end = new Date(Date.now() + 8 * 24 * 3600 * 1000);
    api
      .schedule(start, end)
      .then(setData)
      .catch(() => setFailed(true));
  }, []);

  useEffect(load, [load]);

  async function cancel(a: Appointment) {
    await api.cancel(a.appointment_id);
    load();
  }

  async function noShow(a: Appointment) {
    await api.noShow(a.appointment_id).catch(() => undefined);
    load();
  }

  if (failed) return <p className="notice error">{t("error")}</p>;
  if (!data) return <p className="muted">{t("loading")}</p>;

  const tz = data.timezone;
  const days = upcomingDates(range === "today" ? 1 : 7, tz);
  const byDay = days.map((date) => ({
    date,
    appointments: data.appointments.filter((a) => clinicDate(a.start, tz) === date),
  }));

  return (
    <div className="stack">
      <div className="row spread">
        <h1 style={{ marginBlock: 0 }}>{t("schedule")}</h1>
        <div className="chips" role="group">
          {(["today", "week"] as const).map((r) => (
            <button key={r} className="chip" aria-pressed={range === r} onClick={() => setRange(r)}>
              {t(r === "today" ? "today" : "thisWeek")}
            </button>
          ))}
        </div>
      </div>
      <p className="muted small">
        {t("clinicTime")} ({tz})
      </p>
      <NextPatient />

      {byDay.map(({ date, appointments }) => (
        <section key={date} className="card stack">
          <h3 style={{ marginBlock: 0 }}>{clinicDay(`${date}T12:00:00Z`, tz, locale)}</h3>
          {appointments.length === 0 ? (
            <p className="muted small">{t("noAppointments")}</p>
          ) : (
            appointments.map((a) => (
              <div key={a.appointment_id} className="row spread">
                <div className="appointment">
                  <span className="time">
                    {clinicClock(a.start, tz, locale)} – {clinicClock(a.end, tz, locale)}
                  </span>
                  <span>{a.patient_name ?? <em className="muted">{t("pendingPatient")}</em>}</span>
                  {a.reason_for_visit && <span className="muted small">{a.reason_for_visit}</span>}
                </div>
                <div className="row">
                  <span className={`badge ${a.status}`}>{t(`status_${a.status}`)}</span>
                  {a.status === "confirmed" && new Date(a.start).getTime() > Date.now() && (
                    <button className="danger" onClick={() => cancel(a)}>
                      {t("cancel")}
                    </button>
                  )}
                  {(a.status === "confirmed" || a.status === "completed") && new Date(a.start).getTime() <= Date.now() && (
                    <button className="secondary" onClick={() => noShow(a)}>
                      {t("markNoShow")}
                    </button>
                  )}
                </div>
              </div>
            ))
          )}
        </section>
      ))}
    </div>
  );
}
