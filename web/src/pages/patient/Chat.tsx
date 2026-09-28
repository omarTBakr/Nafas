import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError, type Appointment, type ChatAction, type ChatMessage, type ChatReply } from "../../api";
import { useI18n } from "../../i18n";
import { MicIcon, StopIcon } from "../../icons";
import Markdown from "../../Markdown";
import { recorderType } from "../../recorder";
import { clinicClock, clinicDay } from "../../time";

interface Line {
  id: string;
  role: ChatMessage["role"];
  text: string;
  actions?: ChatAction[];
  // this message has a voice note or a spoken reply to play
  audio?: boolean;
  feedback?: "up" | "down" | null;
}

function fromThread(m: ChatMessage): Line {
  return { id: m.message_id, role: m.role, text: m.content, audio: Boolean(m.audio_key), feedback: m.feedback ?? null };
}

/** Thumbs on one of the assistant's replies: what helps and what does not, read (de-identified) into the evals. */
function Thumbs({ doctorId, line }: { doctorId: string; line: Line }) {
  const { t } = useI18n();
  const [rating, setRating] = useState(line.feedback ?? null);
  async function rate(value: "up" | "down") {
    const before = rating;
    setRating(value);
    try {
      await api.rateReply(doctorId, line.id, value);
    } catch {
      setRating(before);
    }
  }
  return (
    <span className="thumbs" role="group" aria-label={t("rateReply")}>
      <button type="button" className="link" aria-pressed={rating === "up"} aria-label={t("helpful")} onClick={() => rate("up")}>
        👍
      </button>
      <button type="button" className="link" aria-pressed={rating === "down"} aria-label={t("notHelpful")} onClick={() => rate("down")}>
        👎
      </button>
    </span>
  );
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
export default function Chat({
  doctorId,
  timezone,
  onBookingChange: notifyBookingChange,
}: {
  doctorId: string;
  timezone: string;
  onBookingChange: () => void;
}) {
  const { t, reason } = useI18n();
  // The patient's live holds with this doctor, read from their appointments.
  // A reply's cards live only in that reply, so after a reload a hold made in
  // chat would have no Confirm button left; these bring it back.
  const [holds, setHolds] = useState<Appointment[]>([]);
  const loadHolds = useCallback(() => {
    api
      .mine()
      .then((mine) => setHolds(mine.filter((a) => a.doctor_id === doctorId && a.status === "held")))
      .catch(() => setHolds([]));
  }, [doctorId]);
  useEffect(loadHolds, [loadHolds]);
  const onBookingChange = useCallback(() => {
    loadHolds();
    notifyBookingChange();
  }, [loadHolds, notifyBookingChange]);
  const [lines, setLines] = useState<Line[] | null>(null);
  const [draft, setDraft] = useState("");
  const [typing, setTyping] = useState(false);
  const [failed, setFailed] = useState<boolean | "rate_limited">(false);
  const [recording, setRecording] = useState(false);
  const [micDenied, setMicDenied] = useState(false);
  const recorder = useRef<MediaRecorder | null>(null);
  // which consents this chat still needs; null while checking
  const [missing, setMissing] = useState<("data_processing" | "ai_chat")[] | null>(null);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api
      .consents()
      .then((given) => {
        const has = (kind: string, doctor: string | null) => given.some((c) => c.kind === kind && c.doctor_id === doctor);
        setMissing([
          ...(has("data_processing", null) ? [] : (["data_processing"] as const)),
          ...(has("ai_chat", doctorId) ? [] : (["ai_chat"] as const)),
        ]);
      })
      .catch(() => setMissing([]));
    api
      .chatThread(doctorId)
      .then((thread) => setLines(thread.map(fromThread)))
      .catch(() => setLines([]));
  }, [doctorId]);

  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "end" });
  }, [lines, typing]);

  /**
   * Sends one message, typed or spoken: the patient's side shows at once, the
   * reply streams into a live bubble as it is written, and the finished reply
   * (which may differ, and may carry a booking card) replaces it at the end.
   */
  async function deliver(
    pendingText: string,
    voice: boolean,
    run: (onDelta: (text: string) => void) => Promise<ChatReply>,
    onFail: () => void,
  ) {
    setFailed(false);
    const stamp = Date.now();
    const pending: Line = { id: `pending-${stamp}`, role: "patient", text: pendingText };
    const live: Line = { id: `pending-reply-${stamp}`, role: "assistant", text: "" };
    setLines((current) => [...(current ?? []), pending]);
    setTyping(true);
    let streaming = false;
    const onDelta = (piece: string) => {
      setLines((current) => {
        const list = current ?? [];
        if (!streaming) {
          streaming = true;
          setTyping(false);
          return [...list, { ...live, text: piece }];
        }
        return list.map((l) => (l.id === live.id ? { ...l, text: l.text + piece } : l));
      });
    };
    try {
      const reply = await run(onDelta);
      setLines((current) => [
        ...(current ?? []).filter((l) => l.id !== pending.id && l.id !== live.id),
        {
          id: reply.patient_message_id ?? `${reply.message_id}-patient`,
          role: "patient",
          text: reply.patient_text,
          audio: voice && Boolean(reply.patient_message_id),
        },
        { id: reply.message_id, role: "assistant", text: reply.text, actions: reply.actions, audio: Boolean(reply.audio_key) },
      ]);
      if (reply.actions.length > 0) onBookingChange();
    } catch (e) {
      if (e instanceof ApiError && e.reason === "consent_required") setMissing(["data_processing", "ai_chat"]);
      else setFailed(e instanceof ApiError && e.reason === "rate_limited" ? "rate_limited" : true);
      onFail();
      setLines((current) => (current ?? []).filter((l) => l.id !== pending.id && l.id !== live.id));
    } finally {
      setTyping(false);
    }
  }

  async function send(e: React.FormEvent) {
    e.preventDefault();
    const text = draft.trim();
    if (!text || typing) return;
    setDraft("");
    await deliver(text, false, (onDelta) => api.chatSendStreamed(doctorId, text, onDelta), () => setDraft(text));
  }

  async function startRecording() {
    setMicDenied(false);
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setMicDenied(true);
      return;
    }
    const type = recorderType();
    const rec = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
    const chunks: Blob[] = [];
    rec.ondataavailable = (event) => chunks.push(event.data);
    rec.onstop = () => {
      stream.getTracks().forEach((track) => track.stop());
      const note = new Blob(chunks, { type: rec.mimeType || type || "audio/webm" });
      if (note.size > 0)
        void deliver(t("voiceNote"), true, (onDelta) => api.chatVoiceStreamed(doctorId, note, onDelta), () => undefined);
    };
    recorder.current = rec;
    rec.start();
    setRecording(true);
  }

  function stopRecording() {
    recorder.current?.stop();
    recorder.current = null;
    setRecording(false);
  }

  if (lines === null || missing === null) return <p className="muted">{t("loading")}</p>;

  if (missing.length > 0) {
    return (
      <section className="card stack chat" aria-label={t("consents")}>
        <p className="notice info small">{t("aiLabel")}</p>
        {missing.includes("data_processing") && <p>{t("consentDataProcessing")}</p>}
        <p>{t("consentAiChat")}</p>
        <div>
          <button
            onClick={async () => {
              for (const kind of missing) await api.grantConsent(kind, kind === "ai_chat" ? doctorId : undefined);
              setMissing([]);
            }}
          >
            {t("agree")}
          </button>
        </div>
      </section>
    );
  }

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
              {line.role === "patient" ? <p>{line.text}</p> : <Markdown text={line.text} />}
              {line.audio && <audio controls preload="none" src={api.audioUrl(doctorId, line.id)} aria-label={t("voiceNote")} />}
              {line.role === "assistant" && !line.id.startsWith("pending") && <Thumbs doctorId={doctorId} line={line} />}
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
        {holds
          .filter((hold) => !lines.some((line) => line.actions?.some((a) => a.appointment.appointment_id === hold.appointment_id)))
          .map((hold) => (
            <div key={`hold-${hold.appointment_id}`} className="bubble-row assistant">
              <ActionCard action={{ type: "hold", appointment: hold }} timezone={timezone} onChange={onBookingChange} />
            </div>
          ))}
        {typing && <p className="muted small typing">{t("typing")}</p>}
        <div ref={end} />
      </div>
      {failed && (
        <p className="notice warn" role="alert">
          {failed === "rate_limited" ? reason("rate_limited") : t("chatUnavailable")}
        </p>
      )}
      {micDenied && (
        <p className="notice warn" role="alert">
          {t("micDenied")}
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
        <button disabled={typing || recording || !draft.trim()}>{t("send")}</button>
        {recording ? (
          <button type="button" className="danger icon-text" onClick={stopRecording} aria-live="polite">
            <StopIcon />
            {t("stopRecording")}
          </button>
        ) : (
          <button
            type="button"
            className="secondary icon-button"
            onClick={startRecording}
            disabled={typing}
            aria-label={t("record")}
            title={t("record")}
          >
            <MicIcon />
          </button>
        )}
      </form>
      {recording && <p className="muted small">{t("recording")}</p>}
    </section>
  );
}
