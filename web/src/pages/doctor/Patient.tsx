import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, type Timeline, type TimelineItem, uploadDocument, type Visibility, type Visits } from "../../api";
import { type Key, useI18n } from "../../i18n";
import { clinicClock, clinicDay } from "../../time";
import Assistant from "./Assistant";
import RecordVisit from "./RecordVisit";

const KINDS = ["report", "lab", "xray", "ct", "mri", "ultrasound", "prescription", "other"];

function Sharing({ item, onChange }: { item: TimelineItem & { visibility: Visibility }; onChange: () => void }) {
  const { t } = useI18n();
  const shared = item.visibility === "patient_visible";
  const [sourceType, id] = item.type === "document" ? (["document", item.document_id] as const) : (["history", (item as { entry_id: string }).entry_id] as const);
  return (
    <div className="row">
      <span className={`badge ${shared ? "confirmed" : "held"}`}>{shared ? t("shared") : t("doctorOnly")}</span>
      <button
        className="link"
        onClick={async () => {
          await api.setVisibility(sourceType, id, shared ? "doctor_only" : "patient_visible");
          onChange();
        }}
      >
        {shared ? t("unshare") : t("share")}
      </button>
    </div>
  );
}

function Reply({ escalationId, questionId, onDone }: { escalationId: string; questionId: string; onDone: () => void }) {
  const { t } = useI18n();
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  return (
    <form
      className="stack"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setFailed(false);
        try {
          await api.replyToEscalation(escalationId, reply.trim());
          onDone();
        } catch {
          // the answer did not reach the patient: say so, and keep what was written
          setFailed(true);
        } finally {
          setBusy(false);
        }
      }}
    >
      <label>
        {t("yourReply")}
        {/* several questions share this label on one page: say which one this answers */}
        <textarea value={reply} onChange={(e) => setReply(e.target.value)} maxLength={4000} aria-describedby={questionId} />
      </label>
      <div>
        <button disabled={busy || !reply.trim()}>{t("sendReply")}</button>
      </div>
      {failed && (
        <p className="notice error" role="alert">
          {t("error")}
        </p>
      )}
    </form>
  );
}

export function Item({ item, tz, reload }: { item: TimelineItem; tz: string; reload: () => void }) {
  const { t, locale } = useI18n();
  const when = `${clinicDay(item.at, tz, locale)} · ${clinicClock(item.at, tz, locale)}`;
  return (
    <article className={`card stack timeline-item ${item.type}`}>
      <div className="row spread">
        <strong>{item.type === "history" ? t(`kind_${item.kind}` as Key) : t(`item_${item.type}`)}</strong>
        <span className="muted small">{when}</span>
      </div>
      {item.type === "appointment" && (
        <div className="row">
          <span className={`badge ${item.status}`}>{t(`status_${item.status}`)}</span>
          {item.reason_for_visit && <span className="muted">{item.reason_for_visit}</span>}
        </div>
      )}
      {item.type === "history" && item.kind === "visit_transcript" && (
        <details>
          <summary>{t("transcript")}</summary>
          <p className="question transcript-text" dir="auto">
            {item.content}
          </p>
        </details>
      )}
      {item.type === "history" && item.kind !== "visit_transcript" && (
        <>
          <p className="question" dir="auto">{item.content}</p>
          <Sharing item={item} onChange={reload} />
        </>
      )}
      {item.type === "document" && (
        <>
          <div className="row spread">
            <span>{item.filename}</span>
            <span className={`badge ${item.status === "failed" ? "cancelled" : item.status === "indexed" ? "confirmed" : "held"}`}>
              {t(`doc_${item.status}`)}
            </span>
          </div>
          {item.error && <span className="notice error small">{item.error}</span>}
          {item.ai_description && (
            <p className="muted small">
              <em>{item.ai_label}:</em> {item.ai_description}
            </p>
          )}
          <div className="row">
            <button
              className="link"
              onClick={async () => {
                const { url } = await api.documentLink(item.document_id);
                window.open(url, "_blank", "noopener");
              }}
            >
              {t("open")}
            </button>
            <Sharing item={item} onChange={reload} />
          </div>
        </>
      )}
      {item.type === "consultation" && (
        <div className="row spread">
          <span className={`badge ${item.status}`}>{t(`consultation_${item.status}` as Key)}</span>
          <Link to={`/doctor/consultations/${item.consultation_id}`}>{item.status === "draft_ready" ? t("reviewNote") : t("open")}</Link>
        </div>
      )}
      {item.type === "escalation" && (
        <>
          <p className="question" id={`question-${item.escalation_id}`}>
            {item.question}
          </p>
          <span className={`badge ${item.reason === "emergency" ? "cancelled" : "held"}`}>{t(`escalation_${item.reason}`)}</span>
          {item.status === "open" ? <Reply escalationId={item.escalation_id} questionId={`question-${item.escalation_id}`} onDone={reload} /> : item.doctor_reply && <p className="notice ok">{item.doctor_reply}</p>}
        </>
      )}
    </article>
  );
}

export function itemId(item: TimelineItem): string {
  if ("document_id" in item) return item.document_id;
  if ("entry_id" in item) return item.entry_id;
  if ("consultation_id" in item) return item.consultation_id;
  return "";
}

/** A note in the patient's record; filed under a visit when written from its page. */
export function NoteForm({
  patientId,
  appointmentId = null,
  onAdded,
}: {
  patientId: string;
  appointmentId?: string | null;
  onAdded: () => void;
}) {
  const { t } = useI18n();
  const [note, setNote] = useState("");
  const [shared, setShared] = useState(false);
  return (
    <form
      className="card stack"
      onSubmit={async (e) => {
        e.preventDefault();
        await api.addNote(patientId, note.trim(), shared ? "patient_visible" : "doctor_only", "note", appointmentId);
        setNote("");
        onAdded();
      }}
    >
      <label>
        {t("addNote")}
        <textarea value={note} onChange={(e) => setNote(e.target.value)} maxLength={20000} />
      </label>
      <div className="row spread">
        <label className="consent">
          <input type="checkbox" checked={shared} onChange={(e) => setShared(e.target.checked)} />
          <span>{t("shareWithPatient")}</span>
        </label>
        <button disabled={!note.trim()}>{t("addNote")}</button>
      </div>
    </form>
  );
}

/** An upload to the patient's record; filed under a visit when made from its page. */
export function UploadForm({
  patientId,
  appointmentId = null,
  onDone,
}: {
  patientId: string;
  appointmentId?: string | null;
  onDone: () => void;
}) {
  const { t } = useI18n();
  const [kind, setKind] = useState("report");
  const [uploading, setUploading] = useState(false);
  const file = useRef<HTMLInputElement>(null);
  return (
    <div className="card row">
      <label style={{ flex: "1 1 200px" }}>
        {t("chooseFile")}
        <input ref={file} type="file" accept="application/pdf,image/png,image/jpeg,image/webp,image/tiff,text/plain" />
      </label>
      <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="kind" style={{ alignSelf: "end" }}>
        {KINDS.map((k) => (
          <option key={k} value={k}>
            {k}
          </option>
        ))}
      </select>
      <button
        className="secondary"
        style={{ alignSelf: "end" }}
        disabled={uploading}
        onClick={async () => {
          const chosen = file.current?.files?.[0];
          if (!chosen) return;
          setUploading(true);
          try {
            await uploadDocument(patientId, chosen, kind, appointmentId);
            if (file.current) file.current.value = "";
          } finally {
            setUploading(false);
            onDone();
          }
        }}
      >
        {uploading ? t("uploading") : t("upload")}
      </button>
    </div>
  );
}

/** The patient's visits, newest first; each opens on its own page. */
function VisitList({ patientId, visits }: { patientId: string; visits: Visits | null }) {
  const { t, locale } = useI18n();
  if (!visits) return null;
  return (
    <section className="stack" aria-label={t("visits")}>
      <h2>{t("visits")}</h2>
      {visits.visits.length === 0 && <p className="muted">{t("noVisits")}</p>}
      <ul className="visit-list">
        {visits.visits.map((v) => (
          <li key={v.appointment_id}>
            <Link to={`/doctor/patients/${patientId}/visits/${v.appointment_id}`} className="card row spread visit-link">
              <span className="stack">
                <span>
                  {clinicDay(v.start, visits.timezone, locale)} · {clinicClock(v.start, visits.timezone, locale)}
                </span>
                {v.reason_for_visit && (
                  <span className="muted small" dir="auto">
                    {v.reason_for_visit}
                  </span>
                )}
              </span>
              <span className="row">
                <span className={`badge ${v.status}`}>{t(`status_${v.status}`)}</span>
                <span className="muted small">
                  {t("visitRecordings")} {v.recordings} · {t("visitNotes")} {v.notes} · {t("visitDocuments")} {v.documents}
                </span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** One patient's file: their timeline with this doctor, a note, an upload, what they may see, and the assistant beside it. */
export default function Patient() {
  const { patientId } = useParams<{ patientId: string }>();
  const { t } = useI18n();
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [failed, setFailed] = useState(false);
  const [visits, setVisits] = useState<Visits | null>(null);

  const load = useCallback(() => {
    if (!patientId) return;
    api
      .timeline(patientId)
      .then(setTimeline)
      .catch(() => setFailed(true));
    api
      .visits(patientId)
      .then(setVisits)
      .catch(() => setVisits(null));
  }, [patientId]);

  useEffect(load, [load]);

  // a document being read changes status on its own: look again until it settles
  useEffect(() => {
    const reading = timeline?.items.some((i) => i.type === "document" && ["uploaded", "processing"].includes(i.status));
    if (!reading) return;
    const timer = setTimeout(load, 2000);
    return () => clearTimeout(timer);
  }, [timeline, load]);

  if (failed) return <p className="notice error">{t("error")}</p>;
  if (!timeline || !patientId) return <p className="muted">{t("loading")}</p>;

  return (
    <div className="patient-page">
      <div className="stack">
        <header>
          <Link to="/doctor/patients" className="small">
            {t("back")}
          </Link>
          <h1>{timeline.patient.full_name}</h1>
          <p className="muted small">
            {timeline.patient.phone ?? ""} {t("clinicTime")} ({timeline.timezone})
          </p>
        </header>

        <RecordVisit patientId={patientId} onChange={load} />

        <NoteForm patientId={patientId} onAdded={load} />
        <UploadForm patientId={patientId} onDone={load} />

        <VisitList patientId={patientId} visits={visits} />

        <h2>{t("timeline")}</h2>
        {timeline.items.map((item) => (
          <Item key={`${item.type}-${item.at}-${itemId(item)}`} item={item} tz={timeline.timezone} reload={load} />
        ))}
      </div>
      <aside>
        <Assistant patientId={patientId} />
      </aside>
    </div>
  );
}
