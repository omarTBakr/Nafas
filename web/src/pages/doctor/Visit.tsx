import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, type TimelineItem, type VisitDetail } from "../../api";
import { useI18n } from "../../i18n";
import { clinicClock, clinicDay } from "../../time";
import { Item, itemId, NoteForm, UploadForm } from "./Patient";
import RecordVisit from "./RecordVisit";

function Section({ title, items, tz, reload }: { title: string; items: TimelineItem[]; tz: string; reload: () => void }) {
  const { t } = useI18n();
  return (
    <section className="stack" aria-label={title}>
      <h2>{title}</h2>
      {items.length === 0 && <p className="muted">{t("nothingFiled")}</p>}
      {items.map((item) => (
        <Item key={`${item.type}-${itemId(item)}`} item={item} tz={tz} reload={reload} />
      ))}
    </section>
  );
}

/**
 * One visit on its own: the appointment, its recordings and their notes, the
 * notes and documents filed under it; and a recording, note or upload made
 * here is filed under it too.
 */
export default function Visit() {
  const { patientId, appointmentId } = useParams<{ patientId: string; appointmentId: string }>();
  const { t, locale } = useI18n();
  const [visit, setVisit] = useState<VisitDetail | null>(null);
  const [failed, setFailed] = useState<"missing" | "error" | null>(null);

  const load = useCallback(() => {
    if (!patientId || !appointmentId) return;
    api
      .visit(patientId, appointmentId)
      .then(setVisit)
      .catch((e) => setFailed(e?.status === 404 ? "missing" : "error"));
  }, [patientId, appointmentId]);

  useEffect(load, [load]);

  // a document being read changes status on its own: look again until it settles
  useEffect(() => {
    const reading = visit?.documents.some((d) => ["uploaded", "processing"].includes(d.status));
    if (!reading) return;
    const timer = setTimeout(load, 2000);
    return () => clearTimeout(timer);
  }, [visit, load]);

  if (failed) return <p className="notice error">{failed === "missing" ? t("visitNotFound") : t("error")}</p>;
  if (!visit || !patientId || !appointmentId) return <p className="muted">{t("loading")}</p>;

  const tz = visit.timezone;
  const { appointment } = visit;
  const recordings: TimelineItem[] = visit.consultations.map((c) => ({ type: "consultation", at: c.started_at, ...c }));
  const notes: TimelineItem[] = visit.history.map((e) => ({ type: "history", at: e.occurred_at, ...e }));
  const documents: TimelineItem[] = visit.documents.map((d) => ({ type: "document", at: d.created_at, ...d }));

  return (
    <div className="narrow stack">
      <header>
        <Link to={`/doctor/patients/${patientId}`} className="small">
          {t("back")}
        </Link>
        <h1>
          {t("visit")} · {clinicDay(appointment.start, tz, locale)} · {clinicClock(appointment.start, tz, locale)}
        </h1>
        <p className="row">
          <span>{visit.patient.full_name}</span>
          <span className={`badge ${appointment.status}`}>{t(`status_${appointment.status}`)}</span>
          <span className="muted small">{appointment.mode === "online" ? t("online") : t("inPerson")}</span>
          {appointment.reason_for_visit && (
            <span className="muted" dir="auto">
              {appointment.reason_for_visit}
            </span>
          )}
        </p>
      </header>

      <Section title={t("visitRecordings")} items={recordings} tz={tz} reload={load} />
      <Section title={t("visitNotes")} items={notes} tz={tz} reload={load} />
      <Section title={t("visitDocuments")} items={documents} tz={tz} reload={load} />

      <section className="stack" aria-label={t("addToVisit")}>
        <h2>{t("addToVisit")}</h2>
        <p className="muted small">{t("filedUnderVisit")}</p>
        <RecordVisit patientId={patientId} appointmentId={appointmentId} onChange={load} />
        <NoteForm patientId={patientId} appointmentId={appointmentId} onAdded={load} />
        <UploadForm patientId={patientId} appointmentId={appointmentId} onDone={load} />
      </section>
    </div>
  );
}
