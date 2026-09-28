import { useCallback, useEffect, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";

import { api, type HistoryRecord, type PatientSessions, type Session, type Timeline, type TimelineItem } from "../../api";
import { useI18n } from "../../i18n";
import Assistant from "./Assistant";
import { AddMenu, Item, itemId, reading, Reply, SessionCard } from "./sessions";

type Tab = "sessions" | "timeline";
const TAB_KEY = "nafas.patientTab";

function savedTab(): Tab {
  try {
    return localStorage.getItem(TAB_KEY) === "timeline" ? "timeline" : "sessions";
  } catch {
    return "sessions";
  }
}

/** The session opened on arrival: the one the link names, else the latest one that took place and has something in it. */
function openedFirst(sessions: Session[], hash: string): string | null {
  const named = hash.startsWith("#session-") ? hash.slice("#session-".length) : null;
  if (named && sessions.some((s) => s.appointment.appointment_id === named)) return named;
  const now = Date.now();
  const latest = sessions.find(
    (s) => new Date(s.appointment.start).getTime() <= now && s.counts.recordings + s.counts.documents + s.counts.notes > 0,
  );
  return latest?.appointment.appointment_id ?? null;
}

function Questions({ file, reload }: { file: PatientSessions; reload: () => void }) {
  const { t } = useI18n();
  if (file.questions.length === 0) return null;
  return (
    <section className="card stack questions-panel" aria-label={t("openQuestions")}>
      <h2>{t("openQuestions")}</h2>
      {file.questions.map((q) => (
        <div key={q.escalation_id} className="stack">
          <p className="question" id={`question-${q.escalation_id}`} dir="auto">
            {q.question}
          </p>
          <span className={`badge ${q.reason === "emergency" ? "cancelled" : "held"}`}>{t(`escalation_${q.reason}`)}</span>
          <Reply escalationId={q.escalation_id} questionId={`question-${q.escalation_id}`} onDone={reload} />
        </div>
      ))}
    </section>
  );
}

function General({ patientId, file, reload }: { patientId: string; file: PatientSessions; reload: () => void }) {
  const { t } = useI18n();
  const { notes, documents } = file.general;
  const items: TimelineItem[] = [
    ...documents.map((d): TimelineItem => ({ type: "document", at: d.created_at, ...d })),
    ...notes.map((e: HistoryRecord): TimelineItem => ({ type: "history", at: e.occurred_at, ...e })),
  ];
  return (
    <details className="card session" open={file.sessions.length === 0}>
      <summary>
        <span className="row spread session-head">
          <strong>{t("notTiedToSession")}</strong>
          <span className="muted small">
            {t("visitDocuments")} {documents.length} · {t("visitNotes")} {notes.length}
          </span>
        </span>
      </summary>
      <div className="stack session-body">
        {items.length === 0 && <p className="muted small">{t("nothingFiled")}</p>}
        {items.map((item) => (
          <Item key={`${item.type}-${itemId(item)}`} item={item} tz={file.timezone} reload={reload} />
        ))}
        <AddMenu patientId={patientId} onChange={reload} />
      </div>
    </details>
  );
}

/** One patient's file, by session: what needs an answer first, then each visit, then what belongs to none; the assistant beside it. */
export default function Patient() {
  const { patientId } = useParams<{ patientId: string }>();
  const { hash } = useLocation();
  const { t } = useI18n();
  const [file, setFile] = useState<PatientSessions | null>(null);
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [tab, setTab] = useState<Tab>(savedTab);
  const [failed, setFailed] = useState(false);

  const load = useCallback(() => {
    if (!patientId) return;
    api
      .visits(patientId)
      .then(setFile)
      .catch(() => setFailed(true));
  }, [patientId]);

  useEffect(load, [load]);

  // the full timeline, only once asked for
  useEffect(() => {
    if (tab !== "timeline" || !patientId) return;
    api
      .timeline(patientId)
      .then(setTimeline)
      .catch(() => setFailed(true));
  }, [tab, patientId, file]);

  // a document being read changes status on its own: look again until it settles
  useEffect(() => {
    if (!file) return;
    const all = [...file.general.documents, ...file.sessions.flatMap((s) => s.documents)];
    if (!reading(all)) return;
    const timer = setTimeout(load, 2000);
    return () => clearTimeout(timer);
  }, [file, load]);

  function choose(next: Tab) {
    setTab(next);
    try {
      localStorage.setItem(TAB_KEY, next);
    } catch {
      // a remembered tab is a convenience; without storage the page still works
    }
  }

  if (failed) return <p className="notice error">{t("error")}</p>;
  if (!file || !patientId) return <p className="muted">{t("loading")}</p>;

  const opened = openedFirst(file.sessions, hash);

  return (
    <div className="patient-page">
      <div className="stack">
        <header>
          <Link to="/doctor/patients" className="small">
            {t("back")}
          </Link>
          <h1>{file.patient.full_name}</h1>
          <p className="muted small">
            {file.patient.phone ?? ""} {t("clinicTime")} ({file.timezone})
          </p>
        </header>

        <Questions file={file} reload={load} />

        <div className="tabs" role="tablist">
          {(["sessions", "timeline"] as const).map((name) => (
            <button
              key={name}
              role="tab"
              aria-selected={tab === name}
              className={tab === name ? "tab active" : "tab"}
              onClick={() => choose(name)}
            >
              {t(name)}
            </button>
          ))}
        </div>

        {tab === "sessions" ? (
          <div className="stack" role="tabpanel" aria-label={t("sessions")}>
            {file.sessions.length === 0 && <p className="muted">{t("noSessions")}</p>}
            {file.sessions.map((s) => (
              <SessionCard
                key={s.appointment.appointment_id}
                patientId={patientId}
                session={s}
                tz={file.timezone}
                reload={load}
                open={s.appointment.appointment_id === opened}
              />
            ))}
            <General patientId={patientId} file={file} reload={load} />
          </div>
        ) : (
          <div className="stack" role="tabpanel" aria-label={t("timeline")}>
            {!timeline && <p className="muted">{t("loading")}</p>}
            {timeline?.items.map((item) => (
              <Item key={`${item.type}-${item.at}-${itemId(item)}`} item={item} tz={timeline.timezone} reload={load} />
            ))}
          </div>
        )}
      </div>
      <aside>
        <Assistant patientId={patientId} />
      </aside>
    </div>
  );
}
