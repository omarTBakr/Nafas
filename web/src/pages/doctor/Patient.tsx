import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, type Timeline, type TimelineItem, uploadDocument, type Visibility } from "../../api";
import { useI18n } from "../../i18n";
import { clinicClock, clinicDay } from "../../time";
import Assistant from "./Assistant";

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

function Reply({ escalationId, onDone }: { escalationId: string; onDone: () => void }) {
  const { t } = useI18n();
  const [reply, setReply] = useState("");
  return (
    <form
      className="stack"
      onSubmit={async (e) => {
        e.preventDefault();
        await api.replyToEscalation(escalationId, reply.trim());
        onDone();
      }}
    >
      <label>
        {t("yourReply")}
        <textarea value={reply} onChange={(e) => setReply(e.target.value)} maxLength={4000} />
      </label>
      <div>
        <button disabled={!reply.trim()}>{t("sendReply")}</button>
      </div>
    </form>
  );
}

function Item({ item, tz, reload }: { item: TimelineItem; tz: string; reload: () => void }) {
  const { t, locale } = useI18n();
  const when = `${clinicDay(item.at, tz, locale)} · ${clinicClock(item.at, tz, locale)}`;
  return (
    <article className={`card stack timeline-item ${item.type}`}>
      <div className="row spread">
        <strong>{t(`item_${item.type}`)}</strong>
        <span className="muted small">{when}</span>
      </div>
      {item.type === "appointment" && (
        <div className="row">
          <span className={`badge ${item.status}`}>{t(`status_${item.status}`)}</span>
          {item.reason_for_visit && <span className="muted">{item.reason_for_visit}</span>}
        </div>
      )}
      {item.type === "history" && (
        <>
          <p className="question">{item.content}</p>
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
      {item.type === "escalation" && (
        <>
          <p className="question">{item.question}</p>
          <span className={`badge ${item.reason === "emergency" ? "cancelled" : "held"}`}>{t(`escalation_${item.reason}`)}</span>
          {item.status === "open" ? <Reply escalationId={item.escalation_id} onDone={reload} /> : item.doctor_reply && <p className="notice ok">{item.doctor_reply}</p>}
        </>
      )}
    </article>
  );
}

/** One patient's file: their timeline with this doctor, a note, an upload, what they may see, and the assistant beside it. */
export default function Patient() {
  const { patientId } = useParams<{ patientId: string }>();
  const { t } = useI18n();
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [failed, setFailed] = useState(false);
  const [note, setNote] = useState("");
  const [noteShared, setNoteShared] = useState(false);
  const [kind, setKind] = useState("report");
  const [uploading, setUploading] = useState(false);
  const file = useRef<HTMLInputElement>(null);

  const load = useCallback(() => {
    if (!patientId) return;
    api
      .timeline(patientId)
      .then(setTimeline)
      .catch(() => setFailed(true));
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

        <form
          className="card stack"
          onSubmit={async (e) => {
            e.preventDefault();
            await api.addNote(patientId, note.trim(), noteShared ? "patient_visible" : "doctor_only");
            setNote("");
            load();
          }}
        >
          <label>
            {t("addNote")}
            <textarea value={note} onChange={(e) => setNote(e.target.value)} maxLength={20000} />
          </label>
          <div className="row spread">
            <label className="consent">
              <input type="checkbox" checked={noteShared} onChange={(e) => setNoteShared(e.target.checked)} />
              <span>{t("shareWithPatient")}</span>
            </label>
            <button disabled={!note.trim()}>{t("addNote")}</button>
          </div>
        </form>

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
                await uploadDocument(patientId, chosen, kind);
                if (file.current) file.current.value = "";
              } finally {
                setUploading(false);
                load();
              }
            }}
          >
            {uploading ? t("uploading") : t("upload")}
          </button>
        </div>

        <h2>{t("timeline")}</h2>
        {timeline.items.map((item) => (
          <Item key={`${item.type}-${item.at}-${"document_id" in item ? item.document_id : "entry_id" in item ? item.entry_id : ""}`} item={item} tz={timeline.timezone} reload={load} />
        ))}
      </div>
      <aside>
        <Assistant patientId={patientId} />
      </aside>
    </div>
  );
}
