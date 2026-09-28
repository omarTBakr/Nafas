/**
 * The pieces of a patient's file, shared by the file itself and a session's
 * own page: a record item, sharing, a reply, the add forms, and a session.
 */
import { useRef, useState } from "react";
import { Link } from "react-router-dom";

import { api, type HistoryRecord, type Session, type TimelineItem, uploadDocument, type Visibility } from "../../api";
import { type Key, useI18n } from "../../i18n";
import { clinicClock, clinicDay } from "../../time";
import RecordVisit from "./RecordVisit";

const KINDS = ["report", "lab", "xray", "ct", "mri", "ultrasound", "prescription", "other"];

export function Sharing({ item, onChange }: { item: TimelineItem & { visibility: Visibility }; onChange: () => void }) {
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

export function Reply({ escalationId, questionId, onDone }: { escalationId: string; questionId: string; onDone: () => void }) {
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


const asNote = (e: HistoryRecord): TimelineItem => ({ type: "history", at: e.occurred_at, ...e });

/** Anything being read still: the page looks again until it settles. */
export function reading(documents: { status: string }[]): boolean {
  return documents.some((d) => ["uploaded", "processing"].includes(d.status));
}

/** Record, write or upload: one button, and only the form chosen shows. */
export function AddMenu({
  patientId,
  appointmentId = null,
  onChange,
}: {
  patientId: string;
  appointmentId?: string | null;
  onChange: () => void;
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState<"record" | "note" | "upload" | null>(null);
  const done = () => {
    setOpen(null);
    onChange();
  };
  return (
    <div className="stack add-menu">
      <div className="row">
        <span className="muted small">{appointmentId ? t("addToSession") : t("addToFile")}</span>
        {(["record", "note", "upload"] as const).map((choice) => (
          <button
            key={choice}
            type="button"
            className={open === choice ? "" : "secondary"}
            aria-pressed={open === choice}
            onClick={() => setOpen(open === choice ? null : choice)}
          >
            {t(`add_${choice}`)}
          </button>
        ))}
      </div>
      {open === "record" && <RecordVisit patientId={patientId} appointmentId={appointmentId} onChange={onChange} />}
      {open === "note" && <NoteForm patientId={patientId} appointmentId={appointmentId} onAdded={done} />}
      {open === "upload" && <UploadForm patientId={patientId} appointmentId={appointmentId} onDone={done} />}
    </div>
  );
}

/** The approved note first; the patient's plain-language summary under it; or where the note stands. */
function Summary({ session, reload }: { session: Session; reload: () => void }) {
  const { t } = useI18n();
  const { note, patient } = session.summary;
  const draft = session.recordings.find((r) => r.status === "draft_ready");
  if (!note && !patient) {
    return (
      <p className="muted">
        {t("noSummaryYet")}{" "}
        {draft && <Link to={`/doctor/consultations/${draft.consultation_id}`}>{t("reviewNote")}</Link>}
      </p>
    );
  }
  return (
    <div className="stack">
      {note && (
        <div className="summary-note" dir="auto">
          {note.content.split("\n\n").map((part, i) => (
            <p key={i}>{part}</p>
          ))}
        </div>
      )}
      {patient && (
        <div className="stack patient-summary">
          <strong className="small">{t("patientSummary")}</strong>
          <p dir="auto">{patient.content}</p>
          <Sharing item={asNote(patient) as TimelineItem & { visibility: Visibility }} onChange={reload} />
        </div>
      )}
    </div>
  );
}

/** A part of a session; one with nothing in it is left out, not shown empty. */
function Part({ title, children, empty = false }: { title: string; children: React.ReactNode; empty?: boolean }) {
  if (empty) return null;
  return (
    <section className="stack session-part" aria-label={title}>
      <h3>{title}</h3>
      {children}
    </section>
  );
}

/** One session: its time and state at a glance; opened, its summary, recordings, documents and notes. */
export function SessionCard({
  patientId,
  session,
  tz,
  reload,
  open = false,
}: {
  patientId: string;
  session: Session;
  tz: string;
  reload: () => void;
  open?: boolean;
}) {
  const { t, locale } = useI18n();
  const a = session.appointment;
  const when = `${clinicDay(a.start, tz, locale)} · ${clinicClock(a.start, tz, locale)}`;
  const upcoming = new Date(a.start).getTime() > Date.now() && ["confirmed", "held"].includes(a.status);
  const { recordings, documents, notes } = session.counts;
  const empty = recordings + documents + notes === 0;

  const heading = (
    <span className="row spread session-head">
      <span className="stack">
        <strong>{when}</strong>
        {a.reason_for_visit && (
          <span className="muted small" dir="auto">
            {a.reason_for_visit}
          </span>
        )}
      </span>
      <span className="row">
        {upcoming && <span className="badge confirmed">{t("upcoming")}</span>}
        <span className={`badge ${a.status}`}>{t(`status_${a.status}`)}</span>
        {!empty && (
          <span className="muted small">
            {t("visitRecordings")} {recordings} · {t("visitDocuments")} {documents} · {t("visitNotes")} {notes}
          </span>
        )}
      </span>
    </span>
  );

  // a visit that never happened, with nothing in it, is one quiet line
  if (empty && ["cancelled", "no_show"].includes(a.status)) {
    return (
      <div className="card session compact" id={`session-${a.appointment_id}`}>
        {heading}
      </div>
    );
  }

  return (
    <details className="card session" open={open} id={`session-${a.appointment_id}`}>
      <summary>{heading}</summary>
      <div className="stack session-body">
        <Part title={t("summary")}>
          <Summary session={session} reload={reload} />
        </Part>
        <Part title={t("visitRecordings")} empty={session.recordings.length === 0}>
          {session.recordings.map((r) => (
            <div key={r.consultation_id} className="stack">
              <div className="row spread">
                <span className={`badge ${r.status}`}>{t(`consultation_${r.status}` as Key)}</span>
                <Link to={`/doctor/consultations/${r.consultation_id}`}>
                  {r.status === "draft_ready" ? t("reviewNote") : t("open")}
                </Link>
              </div>
              {r.transcript && (
                <details>
                  <summary>{t("transcript")}</summary>
                  <p className="question transcript-text" dir="auto">
                    {r.transcript.content}
                  </p>
                </details>
              )}
            </div>
          ))}
        </Part>
        <Part title={t("visitDocuments")} empty={session.documents.length === 0}>
          {session.documents.map((d) => (
            <Item key={d.document_id} item={{ type: "document", at: d.created_at, ...d }} tz={tz} reload={reload} />
          ))}
        </Part>
        <Part title={t("visitNotes")} empty={session.notes.length === 0}>
          {session.notes.map((e) => (
            <Item key={e.entry_id} item={asNote(e)} tz={tz} reload={reload} />
          ))}
        </Part>
        {a.status !== "cancelled" && (
          <AddMenu patientId={patientId} appointmentId={a.appointment_id} onChange={reload} />
        )}
      </div>
    </details>
  );
}
