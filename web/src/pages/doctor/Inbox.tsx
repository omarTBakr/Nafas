import { useCallback, useEffect, useState } from "react";

import { api, type Escalation } from "../../api";
import { useI18n } from "../../i18n";

function Question({ item, onAnswered }: { item: Escalation; onAnswered: () => void }) {
  const { t, locale } = useI18n();
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

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
        <strong>{item.patient_name ?? t("unknownPatient")}</strong>
        <span className={`badge ${item.reason === "emergency" ? "cancelled" : "held"}`}>{t(`escalation_${item.reason}`)}</span>
      </div>
      <p className="question">{item.question}</p>
      <span className="muted small">
        {t("waiting")} {since}
        {item.nudged_at && ` · ${t("nudged")}`}
      </span>
      {item.status === "open" ? (
        <>
          <label>
            {t("yourReply")}
            <textarea value={reply} maxLength={4000} onChange={(e) => setReply(e.target.value)} />
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
export default function Inbox() {
  const { t } = useI18n();
  const [open, setOpen] = useState<Escalation[] | null>(null);
  const [answered, setAnswered] = useState<Escalation[]>([]);

  const load = useCallback(() => {
    api
      .escalations(["open"])
      .then(setOpen)
      .catch(() => setOpen([]));
    api
      .escalations(["answered"])
      .then((items) => setAnswered(items.slice(-20).reverse()))
      .catch(() => setAnswered([]));
  }, []);

  useEffect(load, [load]);

  if (!open) return <p className="muted">{t("loading")}</p>;
  return (
    <div className="stack">
      <h1>{t("inbox")}</h1>
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
