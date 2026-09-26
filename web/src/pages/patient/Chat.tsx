import { useEffect, useRef, useState } from "react";

import { api, ApiError, type Appointment, type ChatAction, type ChatMessage } from "../../api";
import { useI18n } from "../../i18n";
import { clinicClock, clinicDay } from "../../time";

interface Line {
  id: string;
  role: ChatMessage["role"];
  text: string;
  actions?: ChatAction[];
}

function fromThread(m: ChatMessage): Line {
  return { id: m.message_id, role: m.role, text: m.content };
}

/** A hold, confirmation or cancellation the assistant made, as a card; a hold can be confirmed right here. */
function ActionCard({ action, timezone, onChange }: { action: ChatAction; timezone: string; onChange: () => void }) {
  const { t, locale, reason } = useI18n();
  const [appointment, setAppointment] = useState<Appointment>(action.appointment);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const label =
    appointment.status === "held"
      ? t("heldInChat")
      : appointment.status === "confirmed"
        ? t("confirmedInChat")
        : t("cancelledInChat");

  async function change(run: () => Promise<Appointment>) {
    setBusy(true);
    setError(null);
    try {
      setAppointment(await run());
      onChange();
    } catch (e) {
      setError(reason(e instanceof ApiError ? e.reason : undefined));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card action-card stack">
      <div className="row spread">
        <strong>{label}</strong>
        <span className={`badge ${appointment.status}`}>{t(`status_${appointment.status}`)}</span>
      </div>
      <span className="time">
        {clinicDay(appointment.start, timezone, locale)} · {clinicClock(appointment.start, timezone, locale)}
      </span>
      {appointment.status === "held" && (
        <div className="row">
          <button disabled={busy} onClick={() => change(() => api.confirm(appointment.appointment_id))}>
            {t("confirm")}
          </button>
          <button className="secondary" disabled={busy} onClick={() => change(() => api.cancel(appointment.appointment_id))}>
            {t("cancel")}
          </button>
        </div>
      )}
      {error && <span className="notice warn">{error}</span>}
    </div>
  );
}

/**
 * The patient's chat with this doctor's assistant. Holds it makes are ordinary
 * appointments: the slot picker, "my appointments" and this card all act on the same rows.
 */
export default function Chat({ doctorId, timezone, onBookingChange }: { doctorId: string; timezone: string; onBookingChange: () => void }) {
  const { t } = useI18n();
  const [lines, setLines] = useState<Line[] | null>(null);
  const [draft, setDraft] = useState("");
  const [typing, setTyping] = useState(false);
  const [failed, setFailed] = useState(false);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api
      .chatThread(doctorId)
      .then((thread) => setLines(thread.map(fromThread)))
      .catch(() => setLines([]));
  }, [doctorId]);

  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "end" });
  }, [lines, typing]);

  async function send(e: React.FormEvent) {
    e.preventDefault();
    const text = draft.trim();
    if (!text || typing) return;
    setDraft("");
    setFailed(false);
    const pending: Line = { id: `pending-${Date.now()}`, role: "patient", text };
    setLines((current) => [...(current ?? []), pending]);
    setTyping(true);
    try {
      const reply = await api.chatSend(doctorId, text);
      setLines((current) => [
        ...(current ?? []).filter((l) => l.id !== pending.id),
        { ...pending, id: `${reply.message_id}-patient` },
        { id: reply.message_id, role: "assistant", text: reply.text, actions: reply.actions },
      ]);
      if (reply.actions.length > 0) onBookingChange();
    } catch {
      setFailed(true);
      setDraft(text);
      setLines((current) => (current ?? []).filter((l) => l.id !== pending.id));
    } finally {
      setTyping(false);
    }
  }

  if (lines === null) return <p className="muted">{t("loading")}</p>;

  return (
    <section className="card stack chat" aria-label={t("tabChat")}>
      <p className="notice info small">{t("aiLabel")}</p>
      <div className="messages" role="log" aria-live="polite">
        {lines.length === 0 && <p className="muted">{t("chatIntro")}</p>}
        {lines.map((line) => (
          <div key={line.id} className={`bubble-row ${line.role}`}>
            <div className={`bubble ${line.role}`}>
              <span className="who small muted">
                {line.role === "patient" ? t("you") : line.role === "doctor" ? t("doctorReply") : t("assistant")}
              </span>
              <p>{line.text}</p>
            </div>
            {line.actions?.map((action) => (
              <ActionCard
                key={`${action.type}-${action.appointment.appointment_id}`}
                action={action}
                timezone={timezone}
                onChange={onBookingChange}
              />
            ))}
          </div>
        ))}
        {typing && <p className="muted small typing">{t("typing")}</p>}
        <div ref={end} />
      </div>
      {failed && (
        <p className="notice warn" role="alert">
          {t("chatUnavailable")}
        </p>
      )}
      <form className="row composer" onSubmit={send}>
        <input
          aria-label={t("messagePlaceholder")}
          placeholder={t("messagePlaceholder")}
          value={draft}
          maxLength={4000}
          onChange={(e) => setDraft(e.target.value)}
        />
        <button disabled={typing || !draft.trim()}>{t("send")}</button>
      </form>
    </section>
  );
}
