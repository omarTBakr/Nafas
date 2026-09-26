import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, ApiError, type Appointment, type BookingInfo, type Doctor, type Slot, type Unavailable } from "../../api";
import { useI18n } from "../../i18n";
import { clinicClock, clinicDay, clinicInstant, upcomingDates } from "../../time";

const DAYS_SHOWN = 14;

function nextDate(date: string): string {
  const [y, m, d] = date.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + 1)).toISOString().slice(0, 10);
}

/** Seconds left until `until`, ticking. */
function useCountdown(until: string | null): number {
  const [left, setLeft] = useState(0);
  useEffect(() => {
    if (!until) return;
    const tick = () => setLeft(Math.max(0, Math.round((new Date(until).getTime() - Date.now()) / 1000)));
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, [until]);
  return left;
}

export default function Book() {
  const { doctorId } = useParams<{ doctorId: string }>();
  const { t, lang, locale, reason } = useI18n();

  const [doctor, setDoctor] = useState<Doctor | null>(null);
  const [info, setInfo] = useState<BookingInfo | null>(null);
  const [blocked, setBlocked] = useState<Unavailable | "error" | null>(null);
  const [day, setDay] = useState<string | null>(null);
  const [slots, setSlots] = useState<Slot[] | null>(null);
  const [exact, setExact] = useState("");
  const [refusal, setRefusal] = useState<{ reason: Unavailable | undefined; suggestions: Slot[] } | null>(null);
  const [visitReason, setVisitReason] = useState("");
  const [hold, setHold] = useState<Appointment | null>(null);
  const [done, setDone] = useState<Appointment | null>(null);
  const [busy, setBusy] = useState(false);
  const secondsLeft = useCountdown(hold?.hold_expires_at ?? null);

  useEffect(() => {
    if (!doctorId) return;
    api.doctor(doctorId).then(setDoctor).catch(() => setBlocked("error"));
    api
      .bookingInfo(doctorId)
      .then((i) => {
        setInfo(i);
        setDay(upcomingDates(1, i.timezone)[0]);
      })
      .catch((e) => setBlocked(e instanceof ApiError && e.reason ? e.reason : "error"));
  }, [doctorId]);

  const loadSlots = useCallback(() => {
    if (!doctorId || !info || !day) return;
    setSlots(null);
    const start = new Date(clinicInstant(day, "00:00", info.timezone));
    const end = new Date(clinicInstant(nextDate(day), "00:00", info.timezone));
    api.slots(doctorId, start, end).then(setSlots).catch(() => setSlots([]));
  }, [doctorId, info, day]);

  useEffect(loadSlots, [loadSlots]);

  async function holdTime(start: string) {
    if (!doctorId) return;
    setBusy(true);
    setRefusal(null);
    try {
      setHold(await api.hold(doctorId, start, visitReason));
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        // taken since the list was loaded, or refused: explain, offer the nearest, refresh
        const check = await api.check(doctorId, start).catch(() => null);
        setRefusal({ reason: e.reason, suggestions: check?.suggestions ?? [] });
        loadSlots();
      } else {
        setRefusal({ reason: undefined, suggestions: [] });
      }
    } finally {
      setBusy(false);
    }
  }

  async function checkExact() {
    if (!doctorId || !info || !day || !exact) return;
    setBusy(true);
    setRefusal(null);
    try {
      const start = clinicInstant(day, exact, info.timezone);
      const result = await api.check(doctorId, start);
      if (result.bookable && result.slot) await holdTime(result.slot.start);
      else setRefusal({ reason: result.reason ?? undefined, suggestions: result.suggestions });
    } catch (e) {
      setRefusal({ reason: e instanceof ApiError ? e.reason : undefined, suggestions: [] });
    } finally {
      setBusy(false);
    }
  }

  async function confirmHold() {
    if (!hold) return;
    setBusy(true);
    try {
      setDone(await api.confirm(hold.appointment_id));
      setHold(null);
    } catch (e) {
      setRefusal({ reason: e instanceof ApiError ? e.reason : undefined, suggestions: [] });
      setHold(null);
      loadSlots();
    } finally {
      setBusy(false);
    }
  }

  async function releaseHold() {
    if (!hold) return;
    await api.cancel(hold.appointment_id).catch(() => undefined);
    setHold(null);
    loadSlots();
  }

  if (blocked) return <p className="notice warn">{blocked === "error" ? t("error") : reason(blocked)}</p>;
  if (!doctor || !info || !day) return <p className="muted">{t("loading")}</p>;

  const tz = info.timezone;
  const doctorName = lang === "ar" ? doctor.full_name_ar : doctor.full_name_en;
  const when = (a: { start: string }) => `${clinicDay(a.start, tz, locale)} · ${clinicClock(a.start, tz, locale)}`;

  if (done) {
    return (
      <section className="card stack" aria-live="polite">
        <p className="notice ok">{t("confirmed")}</p>
        <h2>{doctorName}</h2>
        <p className="time">{when(done)}</p>
        <div className="row">
          <Link className="button" to="/appointments">
            {t("myAppointments")}
          </Link>
          <Link className="button secondary" to="/">
            {t("doctors")}
          </Link>
        </div>
      </section>
    );
  }

  return (
    <div className="stack">
      <header>
        <Link to="/" className="small">
          {t("back")}
        </Link>
        <h1>{doctorName}</h1>
        <p className="muted">
          {lang === "ar" ? doctor.specialization_ar : doctor.specialization_en} · {info.slot_minutes} {t("minutes")} ·{" "}
          {t("clinicTime")} ({tz})
        </p>
      </header>

      {hold ? (
        <section className="card stack" aria-live="polite">
          <h2>{t("holdTitle")}</h2>
          <p className="time">{when(hold)}</p>
          <p className={secondsLeft < 60 ? "notice warn" : "muted"}>
            {t("holdExpires")} {Math.floor(secondsLeft / 60)}:{String(secondsLeft % 60).padStart(2, "0")}
          </p>
          <div className="row">
            <button onClick={confirmHold} disabled={busy || secondsLeft === 0}>
              {t("confirm")}
            </button>
            <button className="secondary" onClick={releaseHold} disabled={busy}>
              {t("cancel")}
            </button>
          </div>
        </section>
      ) : (
        <>
          <section className="card stack">
            <h2>{t("pickDay")}</h2>
            <div className="days" role="group" aria-label={t("pickDay")}>
              {upcomingDates(DAYS_SHOWN, tz).map((date) => {
                const noon = clinicInstant(date, "12:00", tz);
                return (
                  <button
                    key={date}
                    className="day"
                    aria-pressed={date === day}
                    onClick={() => {
                      setDay(date);
                      setRefusal(null);
                    }}
                  >
                    <span className="weekday">{new Intl.DateTimeFormat(locale, { timeZone: tz, weekday: "short" }).format(new Date(noon))}</span>
                    <span className="date">{new Intl.DateTimeFormat(locale, { timeZone: tz, day: "numeric", month: "short" }).format(new Date(noon))}</span>
                  </button>
                );
              })}
            </div>

            <h3>{t("freeTimes")}</h3>
            {slots === null ? (
              <p className="muted">{t("loading")}</p>
            ) : slots.length === 0 ? (
              <p className="muted">{t("noFreeTimes")}</p>
            ) : (
              <div className="slots">
                {slots.map((slot) => (
                  <button key={slot.start} className="slot" disabled={busy} onClick={() => holdTime(slot.start)}>
                    {clinicClock(slot.start, tz, locale)}
                  </button>
                ))}
              </div>
            )}

            <form
              className="row"
              onSubmit={(e) => {
                e.preventDefault();
                checkExact();
              }}
            >
              <label style={{ flex: "1 1 200px" }}>
                {t("exactTime")}
                <input type="time" step={60} value={exact} onChange={(e) => setExact(e.target.value)} required />
              </label>
              <button className="secondary" disabled={busy || !exact} style={{ alignSelf: "end" }}>
                {t("check")}
              </button>
            </form>

            {refusal && (
              <div className="notice warn stack" role="alert">
                <span>{reason(refusal.reason)}</span>
                {refusal.suggestions.length > 0 && (
                  <div className="stack">
                    <span>{t("nearest")}</span>
                    <div className="chips">
                      {refusal.suggestions.map((s) => (
                        <button key={s.start} className="chip" onClick={() => holdTime(s.start)} disabled={busy}>
                          {when(s)}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </section>

          <section className="card">
            <label>
              {t("reasonForVisit")}
              <textarea value={visitReason} maxLength={500} onChange={(e) => setVisitReason(e.target.value)} />
            </label>
          </section>
        </>
      )}
    </div>
  );
}
