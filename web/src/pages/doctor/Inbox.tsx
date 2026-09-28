import { useCallback, useEffect, useId, useState } from "react";

import { api, type Consultation, type Escalation } from "../../api";
import { useI18n } from "../../i18n";

function Question({ item, onAnswered }: { item: Escalation; onAnswered: () => void }) {
  const { t, locale } = useI18n();
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  // every reply box is labelled "Your reply"; these ids tell a screen reader
  // whose question each one answers
  const who = useId();
  const what = useId();

  async function send() {
    setBusy(true);
    setFailed(false);
    try {
      await api.replyToEscalation(item.escalation_id, reply.trim());
      onAnswered();
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  const since = new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(new Date(item.created_at));
  return (
    <article className={`card stack ${item.reason === "emergency" ? "urgent" : ""}`}>
      <div className="row spread">
        <strong id={who}>{item.patient_name ?? t("unknownPatient")}</strong>
        <span className={`badge ${item.reason === "emergency" ? "cancelled" : "held"}`}>{t(`escalation_${item.reason}`)}</span>
      </div>
      <p className="question" id={what}>
        {item.question}
      </p>
      <span className="muted small">
        {t("waiting")} {since}
        {item.nudged_at && ` · ${t("nudged")}`}
      </span>
      {item.status === "open" ? (
        <>
          <label>
            {t("yourReply")}
            <textarea
              value={reply}
              maxLength={4000}
              aria-describedby={`${who} ${what}`}
              onChange={(e) => setReply(e.target.value)}
            />
          </label>
          <div>
            <button disabled={busy || !reply.trim()} onClick={send}>
              {t("sendReply")}
            </button>
          </div>
          {failed && <p className="notice error">{t("error")}</p>}
        </>
      ) : (
        item.doctor_reply && <p className="notice ok">{item.doctor_reply}</p>
      )}
    </article>
  );
}

/** Questions the assistant sent to the doctor instead of answering, oldest first; emergencies stand out. */
const FILTERS = [
  ["open", "filterOpen"],
  ["answered", "filterAnswered"],
  ["expired", "filterExpired"],
] as const;

export default function Inbox() {
  const { t, locale } = useI18n();
  const [filter, setFilter] = useState<(typeof FILTERS)[number][0]>("open");
  const [open, setOpen] = useState<Escalation[] | null>(null);
  const [answered, setAnswered] = useState<Escalation[]>([]);
  const [drafts, setDrafts] = useState<Consultation[]>([]);
  const [names, setNames] = useState<Record<string, string>>({});

  // visit notes waiting for review sit above the questions: they are the doctor's own work to finish
  useEffect(() => {
    api
      .consultationsToReview()
      .then(setDrafts)
      .catch(() => setDrafts([]));
    api
      .patients()
      .then((all) => setNames(Object.fromEntries(all.map((p) => [p.patient_id, p.full_name]))))
      .catch(() => undefined);
  }, []);

  const load = useCallback(() => {
    api
      .escalations([filter])
      .then((items) => setOpen(filter === "open" ? items : items.slice().reverse()))
      .catch(() => setOpen([]));
    if (filter === "open")
      api
        .escalations(["answered"])
        .then((items) => setAnswered(items.slice(-20).reverse()))
        .catch(() => setAnswered([]));
    else setAnswered([]);
  }, [filter]);

  useEffect(load, [load]);

  if (!open) return <p className="muted">{t("loading")}</p>;
  return (
    <div className="stack">
      <div className="row spread">
        <h1 style={{ marginBlock: 0 }}>{t("inbox")}</h1>
        <div className="chips" role="group">
          {FILTERS.map(([value, label]) => (
            <button key={value} className="chip" aria-pressed={filter === value} onClick={() => setFilter(value)}>
              {t(label)}
            </button>
          ))}
        </div>
      </div>
      {drafts.length > 0 && (
        <section className="stack" aria-label={t("notesToReview")}>
          <h2>{t("notesToReview")}</h2>
          {drafts.map((d) => (
            <article key={d.consultation_id} className="card row spread">
              <span>
                <strong>{names[d.patient_id] ?? t("unknownPatient")}</strong>{" "}
                <span className="muted small">{new Date(d.started_at).toLocaleString(locale)}</span>
              </span>
              <a href={`/doctor/consultations/${d.consultation_id}`}>{t("reviewNote")}</a>
            </article>
          ))}
        </section>
      )}
      {open.length === 0 && <p className="muted">{t("inboxEmpty")}</p>}
      {open.map((item) => (
        <Question key={item.escalation_id} item={item} onAnswered={load} />
      ))}
      {answered.length > 0 && (
        <>
          <h2>{t("answeredQuestions")}</h2>
          {answered.map((item) => (
            <Question key={item.escalation_id} item={item} onAnswered={load} />
          ))}
        </>
      )}
    </div>
  );
}
